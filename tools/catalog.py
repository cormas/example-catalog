#!/usr/bin/env python3
"""Check models.txt and generate catalog.json and screenshots/ from it.

    python3 tools/catalog.py check      checks models.txt and every repository it lists
    python3 tools/catalog.py generate   writes catalog.json and screenshots/

models.txt lists one GitHub repository URL per line, sorted and unique. Each
repository holds cormas.json and screenshot.png at its root, on its default
branch. A repository whose files are missing or invalid is reported by
`check`, and left out by `generate`. A network or server failure stops
`generate` without writing anything, so the previous catalog stays valid.
"""

import hashlib
import io
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
URL_PATTERN = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?<!\.git)$")
BASELINE_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*$")
THUMBNAIL_SIZE = 512
BACKGROUND = (240, 240, 240)


class EntryError(Exception):
    """A repository of models.txt that cannot be in the catalog, and why."""


class MissingFile(Exception):
    """A file that the repository does not have."""


def read_urls(text):
    """Return the URLs of models.txt and the list of its format errors."""
    urls, errors = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        if not URL_PATTERN.match(line):
            errors.append(f"line {number}: '{line}' is not a URL like https://github.com/owner/repository")
            continue
        if urls and line.lower() == urls[-1].lower():
            errors.append(f"line {number}: {line} is listed twice")
        elif urls and line.lower() < urls[-1].lower():
            errors.append(f"line {number}: {line} must come before {urls[-1]}, so that the lines stay sorted")
        urls.append(line)
    return urls, errors


def raw_url(repository_url, path):
    return repository_url.replace("https://github.com/", "https://raw.githubusercontent.com/", 1) + "/HEAD/" + path


def fetch_from_github(url):
    """Return the bytes at url. Raise MissingFile for a 404, and let any other failure stop the run."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise MissingFile(url) from error
        raise


def read_model(repository_url, fetch):
    """Return the catalog entry of a repository and its thumbnail, or raise EntryError."""
    try:
        metadata_bytes = fetch(raw_url(repository_url, "cormas.json"))
    except MissingFile:
        raise EntryError(f"{repository_url} has no cormas.json on its default branch")
    try:
        metadata = json.loads(metadata_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EntryError(f"{repository_url}: cormas.json is not valid JSON ({error})")
    if not isinstance(metadata, dict):
        raise EntryError(f"{repository_url}: cormas.json must be an object with baseline and summary")
    baseline = metadata.get("baseline")
    if not isinstance(baseline, str) or not BASELINE_PATTERN.match(baseline):
        raise EntryError(f"{repository_url}: the baseline in cormas.json must be a class name such as Firefighters")
    summary = metadata.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise EntryError(f"{repository_url}: cormas.json has no summary")
    try:
        screenshot = fetch(raw_url(repository_url, "screenshot.png"))
    except MissingFile:
        raise EntryError(f"{repository_url} has no screenshot.png on its default branch")
    try:
        image = thumbnail(screenshot)
    except Exception as error:
        raise EntryError(f"{repository_url}: screenshot.png is not a readable image ({error})")
    entry = {
        "baseline": baseline,
        "summary": summary.strip(),
        "url": repository_url,
        "screenshot": f"screenshots/{baseline}.png",
        "screenshotHash": hashlib.sha256(image).hexdigest(),
    }
    return entry, image


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


def read_models(urls, fetch):
    """Return the entries and thumbnails of the repositories, and the errors of those left out."""
    models, errors, repositories = [], [], {}
    for url in urls:
        try:
            entry, image = read_model(url, fetch)
        except EntryError as error:
            errors.append(str(error))
            continue
        baseline = entry["baseline"]
        if baseline in repositories:
            errors.append(f"{url}: the baseline {baseline} is already the one of {repositories[baseline]}")
            continue
        repositories[baseline] = url
        models.append((entry, image))
    return models, errors


def check(root, fetch):
    """Return every error of models.txt and of the repositories it lists."""
    urls, errors = read_urls((root / "models.txt").read_text(encoding="utf-8"))
    _, model_errors = read_models(urls, fetch)
    return errors + model_errors


def generate(root, fetch):
    """Write catalog.json and screenshots/ from models.txt. Return the errors of the repositories left out."""
    urls, errors = read_urls((root / "models.txt").read_text(encoding="utf-8"))
    if errors:
        raise SystemExit("models.txt is not valid:\n" + "\n".join(errors))
    models, errors = read_models(urls, fetch)
    screenshots = root / "screenshots"
    screenshots.mkdir(exist_ok=True)
    for entry, image in models:
        path = root / entry["screenshot"]
        if not path.exists() or path.read_bytes() != image:
            path.write_bytes(image)
    listed = {Path(entry["screenshot"]).name for entry, _ in models}
    for path in screenshots.iterdir():
        if path.name not in listed:
            path.unlink()
    catalog = {"models": [entry for entry, _ in models]}
    (root / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return errors


def main(arguments):
    if arguments not in (["check"], ["generate"]):
        raise SystemExit(__doc__)
    if arguments == ["check"]:
        errors = check(ROOT, fetch_from_github)
        for error in errors:
            print(f"::error::{error}")
        if errors:
            raise SystemExit(f"{len(errors)} problem(s) found")
        print("models.txt and every repository it lists are valid")
    else:
        for error in generate(ROOT, fetch_from_github):
            print(f"::warning::Left out: {error}")


if __name__ == "__main__":
    main(sys.argv[1:])
