# example-catalog

The catalog of example models that Cormas shows in its model list. Cormas downloads `catalog.json` and `screenshots/` over HTTPS, so the list works offline once downloaded, and installs a model by cloning its repository.

## Adding a model

1. Make sure the model repository has, at its root on its default branch:
   - `cormas.json`: `{ "baseline": "Firefighters", "summary": "One paragraph for the catalog" }`. The baseline is the name of the model and must be unique in the catalog.
   - `screenshot.png`: any size and shape. It is shown as a 512 × 512 thumbnail, scaled to fit and padded with a light grey background.
2. Open a pull request adding the repository URL to `models.txt`, like `https://github.com/cormas/firefighters`, keeping the lines sorted. The **Check** workflow tells you precisely what is wrong, if anything.

Once merged, the **Generate** workflow adds the model to `catalog.json` within a few minutes.

## Files

| File | |
|---|---|
| `models.txt` | Edited by hand: one repository URL per line, sorted and unique. |
| `catalog.json` | Generated, never edited: the baseline, summary, URL, screenshot path and screenshot hash of each model. |
| `screenshots/` | Generated, never edited: one thumbnail per model. |
| `tools/catalog.py` | Checks `models.txt` and generates the catalog. Its tests run with `python3 -m unittest discover tools`. |
| `model-repository/notify-catalog.yml` | The workflow to copy into official model repositories so that they notify the catalog. |
| `.github/workflows/notify.yml` | The reusable workflow it calls. |

## When the catalog is generated

- every night;
- when `models.txt` or `tools/` changes on `main`;
- on demand, with **Actions → Generate → Run workflow**;
- when a model repository changes its `cormas.json` or `screenshot.png` on its default branch.

A repository whose files are missing or invalid is left out, with a warning in the workflow log. A network failure stops the generation and leaves the previous catalog unchanged.

## Setting up the notification from model repositories

Official model repositories notify the catalog with `model-repository/notify-catalog.yml`, copied by hand into their `.github/workflows/`. It only calls the reusable workflow `.github/workflows/notify.yml` of this repository, so a change to the notification is made here once. Modelers' own repositories do not have it. It needs an organization secret:

1. Create a fine-grained personal access token (or a GitHub App token) with access to `cormas/example-catalog` only, and the repository permission **Contents: Read and write**.
2. Add it to the `cormas` organization as the secret `CORMAS_CATALOG_TOKEN`, available to the model repositories.
3. Renew it before it expires. Until then, the catalog still updates every night.

A repository without the secret skips the notification.

## Blocking invalid pull requests

In **Settings → Branches**, protect `main` and require the **check** status check to pass before merging.
