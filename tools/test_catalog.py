"""Tests of catalog.py, with repositories served from dictionaries instead of GitHub.

    python3 -m unittest discover tools
"""

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from PIL import Image

import catalog

FIRE = "https://github.com/cormas/firefighters"
RIVER = "https://github.com/cormas/river"


def png(width, height, color=(200, 0, 0)):
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


class GitHub:
    """Repositories in memory: their refs, and the files of each commit."""

    def __init__(self):
        self.refs, self.files = {}, {}

    def add(self, url, ref, commit, baseline, summary="A model", made_with="1.0-dev", screenshot=None, metadata=None):
        self.refs.setdefault(url, {})[ref] = commit
        self.files[catalog.raw_url(url, commit, "cormas.json")] = metadata if metadata is not None else json.dumps(
            {"baseline": baseline, "summary": summary, "cormas": made_with}).encode()
        self.files[catalog.raw_url(url, commit, "screenshot.png")] = screenshot or png(100, 100)

    def branch(self, url, name, commit, baseline, **options):
        self.add(url, f"refs/heads/{name}", commit, baseline, **options)

    def tag(self, url, name, commit, baseline, **options):
        self.add(url, f"refs/tags/{name}", commit, baseline, **options)

    def refs_of(self, url):
        if url not in self.refs:
            raise catalog.MissingFile(url)
        return self.refs[url]

    def fetch(self, url):
        if url not in self.files:
            raise catalog.MissingFile(url)
        return self.files[url]


class ReadListingTest(unittest.TestCase):

    def test_urls_and_refs_sorted_by_url_are_valid(self):
        text = f"{FIRE} v1.0.0\n{FIRE} v1.1.0\n{RIVER} v1.0.0\n"
        self.assertEqual(catalog.read_listing(text, "1"), ([(FIRE, "v1.0.0"), (FIRE, "v1.1.0"), (RIVER, "v1.0.0")], []))

    def test_versions_of_a_repository_keep_the_order_they_were_added_in(self):
        _, errors = catalog.read_listing(f"{FIRE} v2.0.0\n{FIRE} v1.0.0\n", "1")
        self.assertEqual(errors, [])

    def test_unsorted_urls_are_reported_with_their_line_number(self):
        _, errors = catalog.read_listing(f"{RIVER} dev\n{FIRE} dev\n", "dev")
        self.assertEqual(errors, [f"line 2: {FIRE} must come before {RIVER}, so that the lines stay sorted by URL"])

    def test_a_version_listed_twice_is_reported_whatever_the_case_of_its_url(self):
        _, errors = catalog.read_listing(f"{FIRE} v1.0.0\n{FIRE.replace('fire', 'Fire')} v1.0.0\n", "1")
        self.assertEqual(len(errors), 1)
        self.assertIn("is listed twice", errors[0])

    def test_dev_lists_each_repository_once(self):
        _, errors = catalog.read_listing(f"{FIRE} dev\n{FIRE} main\n", "dev")
        self.assertEqual(errors, [f"line 2: {FIRE} is listed twice, and dev lists each repository once"])

    def test_lines_that_are_not_a_url_and_a_ref_are_reported(self):
        for text_line in ["", FIRE, f"{FIRE}  dev", f"{FIRE} dev extra", f"{FIRE}.git dev", f"{FIRE}/ dev", "cormas/river dev"]:
            _, errors = catalog.read_listing(text_line + "\n", "dev")
            self.assertEqual(len(errors), 1, text_line)
            self.assertIn("line 1", errors[0])


class ResolveTest(unittest.TestCase):

    def setUp(self):
        self.github = GitHub()
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.github.tag(FIRE, "v1.0.0", "c2", "Firefighters")

    def resolve_error(self, ref, line):
        with self.assertRaises(catalog.EntryError) as context:
            catalog.resolve(FIRE, ref, line, self.github.refs_of)
        return str(context.exception)

    def test_dev_resolves_a_branch(self):
        self.assertEqual(catalog.resolve(FIRE, "dev", "dev", self.github.refs_of), "c1")

    def test_a_released_line_resolves_a_tag(self):
        self.assertEqual(catalog.resolve(FIRE, "v1.0.0", "1", self.github.refs_of), "c2")

    def test_dev_refuses_a_tag_and_a_released_line_refuses_a_branch(self):
        self.assertIn("is not a branch", self.resolve_error("v1.0.0", "dev"))
        self.assertIn("is not a tag", self.resolve_error("dev", "1"))

    def test_a_missing_repository_is_reported(self):
        with self.assertRaises(catalog.EntryError) as context:
            catalog.resolve(RIVER, "dev", "dev", self.github.refs_of)
        self.assertIn("does not exist", str(context.exception))


class ReadVersionTest(unittest.TestCase):

    def setUp(self):
        self.github = GitHub()

    def read(self, line="dev"):
        return catalog.read_version(FIRE, "dev", "c1", line, self.github.fetch)

    def entry_error(self, line="dev"):
        with self.assertRaises(catalog.EntryError) as context:
            self.read(line)
        return str(context.exception)

    def test_a_version_holds_its_url_ref_commit_and_the_cormas_it_is_made_with(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters", summary=" Fires spread. ")
        version, baseline, summary, _ = self.read()
        self.assertEqual(version, {"url": FIRE, "ref": "dev", "commit": "c1", "cormas": "1.0-dev"})
        self.assertEqual((baseline, summary), ("Firefighters", "Fires spread."))

    def test_files_are_read_at_the_commit(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.github.files = {url.replace("/c1/", "/c0/"): data for url, data in self.github.files.items()}
        self.assertIn("has no cormas.json", self.entry_error())

    def test_cormas_json_with_a_byte_order_mark_is_read(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters",
                           metadata=b'\xef\xbb\xbf{"baseline": "Firefighters", "summary": "A", "cormas": "1.0"}')
        self.assertEqual(self.read()[1], "Firefighters")

    def test_missing_files_are_reported(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        del self.github.files[catalog.raw_url(FIRE, "c1", "screenshot.png")]
        self.assertIn("has no screenshot.png", self.entry_error())
        self.github.files = {}
        self.assertIn("has no cormas.json", self.entry_error())

    def test_invalid_metadata_is_reported(self):
        cases = {
            b"{ not json": "is not valid JSON",
            b"[]": "must be an object",
            b'{"summary": "A", "cormas": "1.0"}': "baseline in cormas.json must be a class name",
            b'{"baseline": "fire fighters", "summary": "A", "cormas": "1.0"}': "baseline in cormas.json must be a class name",
            b'{"baseline": "Firefighters", "cormas": "1.0"}': "has no summary",
            b'{"baseline": "Firefighters", "summary": " ", "cormas": "1.0"}': "has no summary",
            b'{"baseline": "Firefighters", "summary": "A"}': "which Cormas the model is made with",
            b'{"baseline": "Firefighters", "summary": "A", "cormas": "1.0.0"}': "which Cormas the model is made with",
        }
        for metadata, message in cases.items():
            self.github.branch(FIRE, "dev", "c1", "Firefighters", metadata=metadata)
            self.assertIn(message, self.entry_error(), metadata)

    def test_a_released_line_refuses_a_version_made_with_a_newer_major(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters", made_with="2.0")
        self.assertIn("newer than line 1", self.entry_error("1"))
        self.assertEqual(self.read("2")[0]["cormas"], "2.0")

    def test_an_unreadable_screenshot_is_reported(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters", screenshot=b"not an image")
        self.assertIn("screenshot.png is not a readable image", self.entry_error())


class ThumbnailTest(unittest.TestCase):

    def test_a_wide_image_fills_the_width_and_is_padded_above_and_below(self):
        with Image.open(io.BytesIO(catalog.thumbnail(png(1000, 500)))) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.getpixel((256, 10)), catalog.BACKGROUND)
            self.assertEqual(image.getpixel((256, 256)), (200, 0, 0))
            self.assertEqual(image.getpixel((5, 256)), (200, 0, 0))

    def test_a_small_image_is_scaled_up(self):
        with Image.open(io.BytesIO(catalog.thumbnail(png(64, 128)))) as image:
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.getpixel((256, 5)), (200, 0, 0))
            self.assertEqual(image.getpixel((10, 256)), catalog.BACKGROUND)

    def test_the_same_image_gives_the_same_bytes(self):
        self.assertEqual(catalog.thumbnail(png(300, 200)), catalog.thumbnail(png(300, 200)))


class GenerateTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.github = GitHub()

    def tearDown(self):
        self.directory.cleanup()

    def write_line(self, line, *listings):
        folder = self.root / "versions" / line
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "models.txt").write_text("".join(f"{url} {ref}\n" for url, ref in listings))

    def generate(self):
        return catalog.generate(self.root, self.github.refs_of, self.github.fetch)

    def check(self):
        return catalog.check(self.root, self.github.refs_of, self.github.fetch)

    def catalog_json(self, line):
        return json.loads((self.root / "versions" / line / "catalog.json").read_text())

    def screenshots(self, line):
        return sorted(path.name for path in (self.root / "versions" / line / "screenshots").iterdir())

    def test_generate_writes_the_catalog_and_screenshots_of_each_line(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.github.tag(FIRE, "v1.0.0", "c2", "Firefighters", made_with="1.0")
        self.github.branch(RIVER, "dev", "c3", "River")
        self.write_line("dev", (FIRE, "dev"), (RIVER, "dev"))
        self.write_line("1", (FIRE, "v1.0.0"))
        self.assertEqual(self.generate(), [])
        self.assertEqual(self.catalog_json("dev")["format"], 1)
        self.assertEqual([each["baseline"] for each in self.catalog_json("dev")["models"]], ["Firefighters", "River"])
        self.assertEqual(self.catalog_json("1")["models"][0]["versions"],
                         [{"url": FIRE, "ref": "v1.0.0", "commit": "c2", "cormas": "1.0"}])
        self.assertEqual(self.screenshots("dev"), ["Firefighters.png", "River.png"])
        self.assertEqual(self.screenshots("1"), ["Firefighters.png"])

    def test_the_newest_version_gives_the_summary_and_the_screenshot(self):
        self.github.tag(FIRE, "v1.0.0", "c1", "Firefighters", summary="Old", made_with="1.0", screenshot=png(10, 10, (0, 0, 200)))
        self.github.tag(FIRE, "v1.1.0", "c2", "Firefighters", summary="New", made_with="1.1")
        self.write_line("1", (FIRE, "v1.0.0"), (FIRE, "v1.1.0"))
        self.generate()
        model = self.catalog_json("1")["models"][0]
        self.assertEqual([each["ref"] for each in model["versions"]], ["v1.0.0", "v1.1.0"])
        self.assertEqual(model["summary"], "New")
        screenshot = (self.root / "versions" / "1" / model["screenshot"]).read_bytes()
        self.assertEqual(model["screenshotHash"], hashlib.sha256(screenshot).hexdigest())
        self.assertEqual(screenshot, catalog.thumbnail(png(100, 100)))

    def test_dev_leaves_out_invalid_versions_and_deletes_their_screenshots(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.github.branch(RIVER, "dev", "c2", "River")
        self.write_line("dev", (FIRE, "dev"), (RIVER, "dev"))
        self.generate()
        del self.github.files[catalog.raw_url(RIVER, "c2", "cormas.json")]
        self.assertEqual(self.generate(), [f"line dev: {RIVER} dev has no cormas.json"])
        self.assertEqual([each["baseline"] for each in self.catalog_json("dev")["models"]], ["Firefighters"])
        self.assertEqual(self.screenshots("dev"), ["Firefighters.png"])

    def test_two_repositories_with_the_same_baseline_keep_the_first(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.github.branch(RIVER, "dev", "c2", "Firefighters")
        self.write_line("dev", (FIRE, "dev"), (RIVER, "dev"))
        self.assertEqual(self.generate(), [f"line dev: {RIVER} dev: the baseline Firefighters is already the one of {FIRE}"])
        self.assertEqual(len(self.catalog_json("dev")["models"]), 1)

    def test_a_released_line_whose_recorded_version_disappears_is_left_unchanged(self):
        self.github.tag(FIRE, "v1.0.0", "c1", "Firefighters", made_with="1.0")
        self.github.tag(RIVER, "v1.0.0", "c2", "River", made_with="1.0")
        self.write_line("1", (FIRE, "v1.0.0"))
        self.generate()
        before = self.catalog_json("1")
        self.write_line("1", (RIVER, "v1.0.0"))
        errors = self.generate()
        self.assertIn("line 1: Firefighters v1.0.0 at c1 is in the catalog and would change or disappear, "
                      "but a released line is append-only", errors)
        self.assertIn("line 1 is left unchanged", errors)
        self.assertEqual(self.catalog_json("1"), before)

    def test_a_released_line_whose_tag_moved_is_left_unchanged(self):
        self.github.tag(FIRE, "v1.0.0", "c1", "Firefighters", made_with="1.0")
        self.write_line("1", (FIRE, "v1.0.0"))
        self.generate()
        self.github.tag(FIRE, "v1.0.0", "c9", "Firefighters", made_with="1.0")
        self.assertIn("line 1 is left unchanged", self.generate())
        self.assertEqual(self.catalog_json("1")["models"][0]["versions"][0]["commit"], "c1")
        self.assertEqual(len(self.check()), 1)

    def test_a_released_line_accepts_a_corrected_url(self):
        moved = "https://github.com/cormas/firefighters-model"
        self.github.tag(FIRE, "v1.0.0", "c1", "Firefighters", made_with="1.0")
        self.github.tag(moved, "v1.0.0", "c1", "Firefighters", made_with="1.0")
        self.write_line("1", (FIRE, "v1.0.0"))
        self.generate()
        self.write_line("1", (moved, "v1.0.0"))
        self.assertEqual(self.generate(), [])
        self.assertEqual(self.catalog_json("1")["models"][0]["versions"][0]["url"], moved)

    def test_dev_may_change_its_versions(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.write_line("dev", (FIRE, "dev"))
        self.generate()
        self.github.branch(FIRE, "dev", "c2", "Firefighters")
        self.assertEqual(self.generate(), [])
        self.assertEqual(self.catalog_json("dev")["models"][0]["versions"][0]["commit"], "c2")

    def test_generating_twice_changes_nothing(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.write_line("dev", (FIRE, "dev"))
        self.generate()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.generate()
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)

    def test_a_network_failure_writes_nothing(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.write_line("dev", (FIRE, "dev"))

        def failing_fetch(url):
            raise urllib.error.URLError("no network")

        with self.assertRaises(urllib.error.URLError):
            catalog.generate(self.root, self.github.refs_of, failing_fetch)
        self.assertEqual([path.name for path in (self.root / "versions" / "dev").iterdir()], ["models.txt"])

    def test_an_invalid_models_txt_or_line_writes_nothing(self):
        self.write_line("dev", (RIVER, "dev"), (FIRE, "dev"))
        with self.assertRaises(SystemExit):
            self.generate()
        self.assertFalse((self.root / "versions" / "dev" / "catalog.json").exists())
        self.write_line("dev")
        self.write_line("v1")
        with self.assertRaises(SystemExit) as context:
            self.generate()
        self.assertIn("versions/v1 is not a line", str(context.exception))

    def test_check_reports_format_and_version_errors(self):
        self.github.branch(FIRE, "dev", "c1", "Firefighters")
        self.write_line("dev", (RIVER, "dev"), (FIRE, "dev"))
        self.assertEqual(self.check(), [
            f"versions/dev/models.txt line 2: {FIRE} must come before {RIVER}, so that the lines stay sorted by URL",
            f"line dev: {RIVER} dev: the repository does not exist",
        ])


if __name__ == "__main__":
    unittest.main()
