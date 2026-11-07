# example-catalog

The catalog of example models that Cormas shows in its model list. It has one **line** per Cormas line, in `versions/`:

- `versions/dev/` is read by the Cormas in development (a version such as `1.0.0-dev`). It lists a branch of each model, usually `dev`.
- `versions/1/`, `versions/2/`, ... are read by the releases of each major (`1.0.0`, `1.1.0`, ... all read `versions/1/`). They list tags only, each one a version of the model tested with that major.

Cormas downloads `catalog.json` and `screenshots/` of its line over HTTPS, so the list works offline once downloaded, and installs a model by cloning the version it chooses. Cormas X.Y offers the newest version listed in line X that is made with a Cormas no newer than X.Y. The rules are explained in Cormas' versioning documentation.

## Rules that never change

These rules keep every Cormas release working with its catalog for decades:

- A line folder is never renamed or deleted. A line no longer maintained simply stops changing.
- A released line is **append-only**: the only allowed edits are adding a tag tested with that line and correcting the URL of a repository that moved. A version it offers keeps its commit forever. The **Check** workflow refuses anything else, and **Generate** leaves the line unchanged.
- `catalog.json` holds `"format": 1`. The meaning of its fields never changes. An incompatible format gets a new file name (`catalog-2.json`) written next to the old one.

## Adding a model

1. Make sure the version to list has, at the root of the repository:
   - `cormas.json`: `{ "baseline": "Firefighters", "summary": "One paragraph for the catalog", "cormas": "1.0" }`. The baseline is the name of the model and must be unique in a line. `cormas` is the Cormas the version is made with, written by Cormas itself.
   - `screenshot.png`: any size and shape. It is shown as a 512 × 512 thumbnail, scaled to fit and padded with a light grey background.
2. Open a pull request adding a line to the `models.txt` of the line, such as `https://github.com/cormas/firefighters-model dev` in `versions/dev/models.txt`. Lines are sorted by URL. In `dev`, a repository is listed once, with a branch. In a released line, a repository may be listed several times, with a tag each time, its newest version last. The **Check** workflow tells you precisely what is wrong, if anything.

Once merged, the **Generate** workflow adds the model to the `catalog.json` of the line within a few minutes.

## Releasing Cormas X.0.0

For each example model: run its tests on the release candidate, then either reuse a tag already listed that passes, or merge its `dev` branch into `main` and tag it. Create `versions/X/models.txt` from `versions/dev/models.txt` with those tags instead of `dev`. For a minor release X.Y.0, append the new tags of the models that needed changes to `versions/X/models.txt`.

## Files

| File | |
|---|---|
| `versions/<line>/models.txt` | Edited by hand: one version per line, a repository URL and a ref. |
| `versions/<line>/catalog.json` | Generated, never edited: for each model, its baseline, summary, screenshot path and hash, and its versions (URL, ref, commit and the Cormas it is made with). |
| `versions/<line>/screenshots/` | Generated, never edited: one thumbnail per model, of its newest version. |
| `tools/catalog.py` | Checks the lines and generates the catalogs. Its tests run with `python3 -m unittest discover tools`. |
| `model-repository/notify-catalog.yml` | The workflow to copy into official model repositories so that they notify the catalog. |
| `.github/workflows/notify.yml` | The reusable workflow it calls. |

## When the catalogs are generated

- every night;
- when a `models.txt` or `tools/` changes on `main`;
- on demand, with **Actions → Generate → Run workflow**;
- when a model repository changes its `cormas.json` or `screenshot.png` on any branch.

Files are read at the commit their ref points to. In `dev`, a version whose files are missing or invalid is left out, with a warning in the workflow log. In a released line, a version that would change or disappear leaves the whole line unchanged, with a warning. A network failure stops the generation and leaves every catalog unchanged.

## Setting up the notification from model repositories

Official model repositories notify the catalog with `model-repository/notify-catalog.yml`, copied by hand into their `.github/workflows/`. It only calls the reusable workflow `.github/workflows/notify.yml` of this repository, so a change to the notification is made here once. Modelers' own repositories do not have it. It needs an organization secret:

1. Create a fine-grained personal access token (or a GitHub App token) with access to `cormas/example-catalog` only, and the repository permission **Contents: Read and write**.
2. Add it to the `cormas` organization as the secret `CORMAS_CATALOG_TOKEN`, available to the model repositories.
3. Renew it before it expires. Until then, the catalogs still update every night.

A repository without the secret skips the notification.

## Blocking invalid pull requests

In **Settings → Branches**, protect `main` and require the **check** status check to pass before merging.
