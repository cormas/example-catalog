"""Tests of catalog.py, with repositories served from a dictionary instead of GitHub.

    python3 -m unittest discover tools
"""

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


def repository(url, baseline, summary="A model", screenshot=None):
    return {
        catalog.raw_url(url, "cormas.json"): json.dumps({"baseline": baseline, "summary": summary}).encode(),
        catalog.raw_url(url, "screenshot.png"): screenshot or png(100, 100),
    }


def fetch_from(files):
    def fetch(url):
        if url not in files:
            raise catalog.MissingFile(url)
        return files[url]
    return fetch


class ReadUrlsTest(unittest.TestCase):

    def test_sorted_unique_urls_are_valid(self):
        self.assertEqual(catalog.read_urls(f"{FIRE}\n{RIVER}\n"), ([FIRE, RIVER], []))

    def test_unsorted_lines_are_reported_with_their_number(self):
        _, errors = catalog.read_urls(f"{RIVER}\n{FIRE}\n")
        self.assertEqual(errors, [f"line 2: {FIRE} must come before {RIVER}, so that the lines stay sorted"])

    def test_a_url_listed_twice_is_reported_whatever_its_case(self):
        _, errors = catalog.read_urls(f"{FIRE}\n{FIRE.replace('firefighters', 'Firefighters')}\n")
        self.assertEqual(len(errors), 1)
        self.assertIn("listed twice", errors[0])

    def test_lines_that_are_not_repository_urls_are_reported(self):
        for line in ["", FIRE + ".git", FIRE + "/", "http://github.com/cormas/river", "cormas/river"]:
            _, errors = catalog.read_urls(line + "\n")
            self.assertEqual(len(errors), 1, line)
            self.assertIn("line 1", errors[0])


class ReadModelTest(unittest.TestCase):

    def entry_error(self, files):
        with self.assertRaises(catalog.EntryError) as context:
            catalog.read_model(FIRE, fetch_from(files))
        return str(context.exception)

    def test_entry_holds_the_metadata_and_the_thumbnail_hash(self):
        entry, image = catalog.read_model(FIRE, fetch_from(repository(FIRE, "Firefighters", " Fires spread. ")))
        self.assertEqual(entry["baseline"], "Firefighters")
        self.assertEqual(entry["summary"], "Fires spread.")
        self.assertEqual(entry["url"], FIRE)
        self.assertEqual(entry["screenshot"], "screenshots/Firefighters.png")
        self.assertEqual(entry["screenshotHash"], __import__("hashlib").sha256(image).hexdigest())

    def test_cormas_json_with_a_byte_order_mark_is_read(self):
        files = repository(FIRE, "Firefighters")
        files[catalog.raw_url(FIRE, "cormas.json")] = b"\xef\xbb\xbf" + files[catalog.raw_url(FIRE, "cormas.json")]
        entry, _ = catalog.read_model(FIRE, fetch_from(files))
        self.assertEqual(entry["baseline"], "Firefighters")

    def test_missing_files_are_reported(self):
        files = repository(FIRE, "Firefighters")
        del files[catalog.raw_url(FIRE, "screenshot.png")]
        self.assertIn("has no screenshot.png", self.entry_error(files))
        self.assertIn("has no cormas.json", self.entry_error({}))

    def test_invalid_metadata_is_reported(self):
        cases = {
            b"{ not json": "is not valid JSON",
            b"[]": "must be an object",
            b'{"summary": "A model"}': "baseline in cormas.json must be a class name",
            b'{"baseline": "fire fighters", "summary": "A model"}': "baseline in cormas.json must be a class name",
            b'{"baseline": "Firefighters"}': "has no summary",
            b'{"baseline": "Firefighters", "summary": " "}': "has no summary",
        }
        for metadata, message in cases.items():
            files = repository(FIRE, "Firefighters")
            files[catalog.raw_url(FIRE, "cormas.json")] = metadata
            self.assertIn(message, self.entry_error(files), metadata)

    def test_an_unreadable_screenshot_is_reported(self):
        files = repository(FIRE, "Firefighters", screenshot=b"not an image")
        self.assertIn("screenshot.png is not a readable image", self.entry_error(files))


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

    def tearDown(self):
        self.directory.cleanup()

    def write_models(self, *urls):
        (self.root / "models.txt").write_text("".join(url + "\n" for url in urls))

    def catalog_json(self):
        return json.loads((self.root / "catalog.json").read_text())

    def test_generate_writes_the_catalog_and_the_screenshots(self):
        self.write_models(FIRE, RIVER)
        files = {**repository(FIRE, "Firefighters"), **repository(RIVER, "River")}
        self.assertEqual(catalog.generate(self.root, fetch_from(files)), [])
        self.assertEqual([each["baseline"] for each in self.catalog_json()["models"]], ["Firefighters", "River"])
        self.assertEqual(sorted(path.name for path in (self.root / "screenshots").iterdir()), ["Firefighters.png", "River.png"])

    def test_generate_leaves_out_invalid_repositories_and_deletes_their_screenshots(self):
        self.write_models(FIRE, RIVER)
        files = {**repository(FIRE, "Firefighters"), **repository(RIVER, "River")}
        catalog.generate(self.root, fetch_from(files))
        del files[catalog.raw_url(RIVER, "cormas.json")]
        errors = catalog.generate(self.root, fetch_from(files))
        self.assertEqual(errors, [f"{RIVER} has no cormas.json on its default branch"])
        self.assertEqual([each["baseline"] for each in self.catalog_json()["models"]], ["Firefighters"])
        self.assertEqual([path.name for path in (self.root / "screenshots").iterdir()], ["Firefighters.png"])

    def test_two_repositories_with_the_same_baseline_keep_the_first(self):
        self.write_models(FIRE, RIVER)
        files = {**repository(FIRE, "Firefighters"), **repository(RIVER, "Firefighters")}
        errors = catalog.generate(self.root, fetch_from(files))
        self.assertEqual(errors, [f"{RIVER}: the baseline Firefighters is already the one of {FIRE}"])
        self.assertEqual([each["url"] for each in self.catalog_json()["models"]], [FIRE])

    def test_generating_twice_changes_nothing(self):
        self.write_models(FIRE)
        files = repository(FIRE, "Firefighters")
        catalog.generate(self.root, fetch_from(files))
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        catalog.generate(self.root, fetch_from(files))
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}, before)

    def test_a_network_failure_writes_nothing(self):
        self.write_models(FIRE)

        def failing_fetch(url):
            raise urllib.error.URLError("no network")

        with self.assertRaises(urllib.error.URLError):
            catalog.generate(self.root, failing_fetch)
        self.assertEqual([path.name for path in self.root.iterdir()], ["models.txt"])

    def test_an_invalid_models_txt_writes_nothing(self):
        self.write_models(RIVER, FIRE)
        with self.assertRaises(SystemExit):
            catalog.generate(self.root, fetch_from({}))
        self.assertFalse((self.root / "catalog.json").exists())

    def test_check_reports_format_and_repository_errors(self):
        self.write_models(RIVER, FIRE)
        errors = catalog.check(self.root, fetch_from(repository(FIRE, "Firefighters")))
        self.assertEqual(errors, [
            f"line 2: {FIRE} must come before {RIVER}, so that the lines stay sorted",
            f"{RIVER} has no cormas.json on its default branch",
        ])


if __name__ == "__main__":
    unittest.main()
