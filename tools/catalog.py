#!/usr/bin/env python3
"""Check the catalog lines and generate their catalog.json and screenshots/.

    python3 tools/catalog.py check      checks every line and the repositories it lists
    python3 tools/catalog.py generate   writes catalog.json and screenshots/ of every line

The catalog has one line per Cormas line in versions/: dev, read by the
Cormas in development, and 1, 2, ... read by the releases of each major.
versions/<line>/models.txt lists one model version per line: a repository URL
and a ref, separated by a space. In dev the ref is a branch and each
repository is listed once. In a released line the ref is a tag, a repository
may be listed several times, its newest version last, and the line is
append-only: a version recorded in catalog.json must stay, at the same commit
(its URL may be corrected). Lines are sorted by URL.

Each version holds cormas.json and screenshot.png at its root. A version
whose files are missing or invalid is reported by `check`. In dev, `generate`
leaves it out. In a released line, `generate` leaves the whole line unchanged
when a version it recorded would change or disappear. A network or server
failure stops `generate` before anything is written.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
FORMAT = 1
LINE_PATTERN = re.compile(r"^(dev|[1-9][0-9]*)$")
URL_PATTERN = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?<!\.git)$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
BASELINE_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*$")
MADE_WITH_PATTERN = re.compile(r"^([0-9]+)\.([0-9]+)(-dev)?$")
THUMBNAIL_SIZE = 512
BACKGROUND = (240, 240, 240)


class EntryError(Exception):
    """A version of models.txt that cannot be in the catalog, and why."""


class MissingFile(Exception):
    """A file or repository that does not exist."""


def is_released(line):
    return line != "dev"


def read_listing(text, line):
    """Return the (URL, ref) pairs of a models.txt and the list of its format errors."""
    listings, errors = [], []
    for number, text_line in enumerate(text.splitlines(), start=1):
        parts = text_line.split(" ")
        if len(parts) != 2 or not URL_PATTERN.match(parts[0]) or not REF_PATTERN.match(parts[1]):
            errors.append(f"line {number}: '{text_line}' is not a URL and a ref, like https://github.com/owner/repository v1.0.0")
            continue
        url, ref = parts
        previous = [each for each, _ in listings]
        if (url.lower(), ref) in [(each.lower(), each_ref) for each, each_ref in listings]:
            errors.append(f"line {number}: {url} {ref} is listed twice")
        elif not is_released(line) and url.lower() in [each.lower() for each in previous]:
            errors.append(f"line {number}: {url} is listed twice, and dev lists each repository once")
        elif previous and url.lower() < previous[-1].lower():
            errors.append(f"line {number}: {url} must come before {previous[-1]}, so that the lines stay sorted by URL")
        listings.append((url, ref))
    return listings, errors


def raw_url(repository_url, commit, path):
    return f"{repository_url.replace('https://github.com/', 'https://raw.githubusercontent.com/', 1)}/{commit}/{path}"


def fetch_from_github(url):
    """Return the bytes at url. Raise MissingFile for a 404, and let any other failure stop the run."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise MissingFile(url) from error
        raise


def refs_from_github(repository_url):
    """Return the branches and tags of a repository as {'refs/heads/dev': commit, 'refs/tags/v1.0.0': commit}, a tag giving the commit it points to."""
    result = subprocess.run(["git", "ls-remote", "--heads", "--tags", repository_url + ".git"],
                            capture_output=True, text=True, timeout=120,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode != 0:
        if "not found" in result.stderr.lower() or "could not read username" in result.stderr.lower():
            # GitHub asks for credentials for a repository that does not exist or is private: neither can be in the catalog
            raise MissingFile(repository_url)
        raise RuntimeError(f"git ls-remote {repository_url} failed: {result.stderr.strip()}")
    refs = {}
    for text_line in result.stdout.splitlines():
        commit, name = text_line.split("\t")
        if name.endswith("^{}"):
            refs[name[:-3]] = commit
        else:
            refs.setdefault(name, commit)
    return refs


def resolve(repository_url, ref, line, refs_of):
    """Return the commit of the ref: a branch in dev, a tag in a released line. Raise EntryError otherwise."""
    try:
        refs = refs_of(repository_url)
    except MissingFile:
        raise EntryError(f"{repository_url} {ref}: the repository does not exist")
    kind, name = ("tags", "a tag") if is_released(line) else ("heads", "a branch")
    commit = refs.get(f"refs/{kind}/{ref}")
    if commit is None:
        raise EntryError(f"{repository_url} {ref}: {ref} is not {name} of the repository, and line {line} lists only {kind.replace('heads', 'branches')}")
    return commit


def read_version(repository_url, ref, commit, line, fetch):
    """Return the version, its baseline and summary, and its thumbnail, or raise EntryError."""
    name = f"{repository_url} {ref}"
    try:
        metadata_bytes = fetch(raw_url(repository_url, commit, "cormas.json"))
    except MissingFile:
        raise EntryError(f"{name} has no cormas.json")
    try:
        metadata = json.loads(metadata_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EntryError(f"{name}: cormas.json is not valid JSON ({error})")
    if not isinstance(metadata, dict):
        raise EntryError(f"{name}: cormas.json must be an object with baseline, summary and cormas")
    baseline = metadata.get("baseline")
    if not isinstance(baseline, str) or not BASELINE_PATTERN.match(baseline):
        raise EntryError(f"{name}: the baseline in cormas.json must be a class name such as Firefighters")
    summary = metadata.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise EntryError(f"{name}: cormas.json has no summary")
    made_with = metadata.get("cormas")
    match = MADE_WITH_PATTERN.match(made_with) if isinstance(made_with, str) else None
    if not match:
        raise EntryError(f"{name}: cormas.json must say which Cormas the model is made with, such as \"cormas\": \"1.0\"")
    if is_released(line) and int(match.group(1)) > int(line):
        raise EntryError(f"{name} is made with Cormas {made_with}, newer than line {line}")
    try:
        screenshot = fetch(raw_url(repository_url, commit, "screenshot.png"))
    except MissingFile:
        raise EntryError(f"{name} has no screenshot.png")
    try:
        image = thumbnail(screenshot)
    except Exception as error:
        raise EntryError(f"{name}: screenshot.png is not a readable image ({error})")
    version = {"url": repository_url, "ref": ref, "commit": commit, "cormas": made_with}
    return version, baseline, summary.strip(), image


def thumbnail(image_bytes):
    """Return a square PNG showing the whole image, scaled to fit and padded with a neutral background."""
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGBA")
    image = ImageOps.contain(image, (THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.LANCZOS)
    square = Image.new("RGB", (THUMBNAIL_SIZE, THUMBNAIL_SIZE), BACKGROUND)
    square.paste(image, ((THUMBNAIL_SIZE - image.width) // 2, (THUMBNAIL_SIZE - image.height) // 2), image)
    output = io.BytesIO()
    square.save(output, format="PNG")
    return output.getvalue()


def read_models(listings, line, refs_of, fetch):
    """Return the models of a line, each with its versions in the order of models.txt and the thumbnail of its newest version, and the errors of the versions left out."""
    models, errors = {}, []
    for url, ref in listings:
        try:
            commit = resolve(url, ref, line, refs_of)
            version, baseline, summary, image = read_version(url, ref, commit, line, fetch)
        except EntryError as error:
            errors.append(str(error))
            continue
        model = models.get(baseline)
        if model and model["entry"]["versions"][0]["url"].lower() != url.lower():
            errors.append(f"{url} {ref}: the baseline {baseline} is already the one of {model['entry']['versions'][0]['url']}")
            continue
        if not model:
            model = models[baseline] = {"entry": {"baseline": baseline, "versions": []}}
        model["entry"].update({
            "summary": summary,
            "screenshot": f"screenshots/{baseline}.png",
            "screenshotHash": hashlib.sha256(image).hexdigest(),
        })
        model["entry"]["versions"].append(version)
        model["image"] = image
    return [(model["entry"], model["image"]) for model in models.values()], errors


def recorded_versions(catalog):
    return {(model["baseline"], version["ref"], version["commit"]) for model in catalog["models"] for version in model["versions"]}


def removed_versions(line_folder, models):
    """Return the errors for the versions that the catalog.json of a released line records and the new catalog would not."""
    catalog_file = line_folder / "catalog.json"
    if not catalog_file.exists():
        return []
    before = recorded_versions(json.loads(catalog_file.read_text(encoding="utf-8")))
    after = recorded_versions({"models": [entry for entry, _ in models]})
    return [f"line {line_folder.name}: {baseline} {ref} at {commit[:12]} is in the catalog and would change or disappear, "
            f"but a released line is append-only"
            for baseline, ref, commit in sorted(before - after)]


def read_lines(root):
    """Return the folders of the lines and their listings. Stop at the first invalid line or models.txt."""
    errors, lines = [], []
    for folder in sorted((root / "versions").iterdir()):
        if not folder.is_dir():
            continue
        if not LINE_PATTERN.match(folder.name):
            errors.append(f"versions/{folder.name} is not a line: a line is dev or a major such as 1")
            continue
        listings, listing_errors = read_listing((folder / "models.txt").read_text(encoding="utf-8"), folder.name)
        errors += [f"versions/{folder.name}/models.txt {error}" for error in listing_errors]
        lines.append((folder, listings))
    return lines, errors


def check(root, refs_of, fetch):
    """Return every error of the lines and of the versions they list."""
    lines, errors = read_lines(root)
    for folder, listings in lines:
        models, model_errors = read_models(listings, folder.name, refs_of, fetch)
        errors += [f"line {folder.name}: {error}" for error in model_errors]
        if is_released(folder.name):
            errors += removed_versions(folder, models)
    return errors


def generate(root, refs_of, fetch):
    """Write catalog.json and screenshots/ of every line. Return the errors of what was left out."""
    lines, errors = read_lines(root)
    if errors:
        raise SystemExit("The catalog lines are not valid:\n" + "\n".join(errors))
    results = []
    for folder, listings in lines:
        models, model_errors = read_models(listings, folder.name, refs_of, fetch)
        errors += [f"line {folder.name}: {error}" for error in model_errors]
        removed = removed_versions(folder, models) if is_released(folder.name) else []
        if removed:
            errors += removed + [f"line {folder.name} is left unchanged"]
        else:
            results.append((folder, models))
    for folder, models in results:
        write_line(folder, models)
    return errors


def write_line(folder, models):
    screenshots = folder / "screenshots"
    screenshots.mkdir(exist_ok=True)
    for entry, image in models:
        path = folder / entry["screenshot"]
        if not path.exists() or path.read_bytes() != image:
            path.write_bytes(image)
    listed = {Path(entry["screenshot"]).name for entry, _ in models}
    for path in screenshots.iterdir():
        if path.name not in listed:
            path.unlink()
    catalog = {"format": FORMAT, "models": [entry for entry, _ in models]}
    (folder / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(arguments):
    if arguments not in (["check"], ["generate"]):
        raise SystemExit(__doc__)
    if arguments == ["check"]:
        errors = check(ROOT, refs_from_github, fetch_from_github)
        for error in errors:
            print(f"::error::{error}")
        if errors:
            raise SystemExit(f"{len(errors)} problem(s) found")
        print("Every line and every version it lists are valid")
    else:
        for error in generate(ROOT, refs_from_github, fetch_from_github):
            print(f"::warning::{error}")


if __name__ == "__main__":
    main(sys.argv[1:])
