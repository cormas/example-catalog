# example-catalog

The catalog of example models that Cormas shows in its model list.

**How examples are released and how the catalog is maintained, with the rules that must never be broken, is explained in [Examples and the catalog](https://cormas.org/docs/community/examples-and-catalog).** Read it before changing an example or this repository. This README only describes how the repository works.

## Lines

The catalog has one **line** per major of Cormas, in `versions/`:

- `versions/dev/` is read by Cormas in development, such as `1.1.0-dev`. It lists each example once, with its branch `dev`.
- `versions/1/`, `versions/2/`, ... are read by every release of that major (`1.0.0`, `1.1.0`, ... all read `versions/1/`). They list released versions only: tags, named after the day of their release, such as `2027.03.14`.

Cormas downloads `catalog.json` and `screenshots/` of its line over HTTPS, so the list works offline once downloaded, and installs an example by cloning the version it chooses.

## `models.txt`

The only file edited by hand, one per line. Each row is one version: the URL of a repository and a ref, separated by a space.

```text
https://github.com/cormas/firefighters-model 2027.01.20
https://github.com/cormas/firefighters-model 2027.03.14
```

- Rows are sorted by URL.
- In `dev`, a repository is listed once, with a branch.
- In a released line, a repository may be listed several times, with a tag each time, its newest version last. A released version is appended to the line of the major it is made with (the `cormas` field of its `cormas.json`).
- A released line is append-only: a version it lists keeps its commit forever. The only other allowed change is correcting the URL of a repository that moved.

Each version needs, at the root of its repository:

- `cormas.json`, such as `{ "baseline": "Firefighters", "summary": "One paragraph for the catalog", "cormas": "1.0" }`. The baseline is the name of the model and must be unique in a line. `cormas` is the Cormas the version is made with, written by Cormas itself.
- `screenshot.png`, of any size and shape. It is shown as a 512 × 512 thumbnail, scaled to fit and padded with a light grey background.

## Workflows

**Check** runs on every pull request and refuses what breaks the rules above, saying precisely what is wrong.

**Generate** writes `catalog.json` and `screenshots/` of every line:

- every night;
- when a `models.txt` or `tools/` changes on `main`;
- on demand, with **Actions → Generate → Run workflow**;
- when an official example changes its `cormas.json` or `screenshot.png` on any branch.

Files are read at the commit their ref points to. In `dev`, a version whose files are missing or invalid is left out, with a warning in the workflow log. In a released line, a version that would change or disappear leaves the whole line unchanged, with a warning. A network failure stops the generation and leaves every catalog unchanged.

`catalog.json` holds `"format": 1`. The meaning of its fields never changes; an incompatible format gets a new file name, such as `catalog-2.json`, written next to the old one.

## Files

| File | |
|---|---|
| `versions/<line>/models.txt` | Edited by hand: one version per row. |
| `versions/<line>/catalog.json` | Generated, never edited: for each model, its baseline, summary, screenshot path and hash, and its versions (URL, ref, commit and the Cormas it is made with). |
| `versions/<line>/screenshots/` | Generated, never edited: one thumbnail per model, of its newest version. |
| `tools/catalog.py` | Checks the lines and generates the catalogs. Its tests run with `python3 -m unittest discover tools`. |
| `model-repository/notify-catalog.yml` | The workflow to copy into official example repositories, so that they notify the catalog. |
| `.github/workflows/notify.yml` | The reusable workflow it calls. |

## Setting up the notification from example repositories

Official example repositories notify the catalog with `model-repository/notify-catalog.yml`, copied by hand into their `.github/workflows/`. It only calls the reusable workflow `.github/workflows/notify.yml` of this repository, so a change to the notification is made here once. Modelers' own repositories do not have it. It needs an organization secret:

1. Create a fine-grained personal access token (or a GitHub App token) with access to `cormas/example-catalog` only, and the repository permission **Contents: Read and write**.
2. Add it to the `cormas` organization as the secret `CORMAS_CATALOG_TOKEN`, available to the example repositories.
3. Renew it before it expires. Until then, the catalogs still update every night.

A repository without the secret skips the notification.

## Protecting this repository

In **Settings → Rules → Rulesets**, add a branch ruleset on `main`, with an empty **Bypass list**, that requires a pull request and the **check** status check before merging.
