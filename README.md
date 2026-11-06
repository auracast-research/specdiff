# Bluetooth Core Specification changes

> Hi, I'm a human, but all the rest in here was done by a LLM instructed by me. The results look fine, but I haven't read the code.

What changed in the Bluetooth Core Specification from 4.2 to 7.0, section by section and
sentence by sentence: new sections and protocols, and also the single sentence added to a
section that has been there for ten years. [CONCEPT.md](CONCEPT.md) explains the idea and
the views; this file explains how to run it.

A page with three views and a panel:

- **Changes**: the changes between two versions, ranked so that a *should* becoming
  *shall* comes before a long rewrite, and edits to old sections before new sections.
  Filters for small edits in old sections, larger edits, new and removed sections; for
  changes to *shall*, *should* and *may*, negations and values; and for a Part. The search
  covers headings, all the changed text and section numbers.
- **Map**: every section of every version (or only those changed in the range), as a line
  from the version that added it to the last that has it, with a mark for each change.
- **Sweeping edits**: replacements a version made everywhere (`master` → `central` in
  5.3, `The HCI_Reset command` → `This` in 6.1). They are learnt from the data and counted
  as editorial, so they don't drown the real changes; each lists where it applied, and any
  can be counted as a change instead.
- **The panel**: a section's life across all versions, its word-level diff (for a range,
  all at once or step by step), and its blame (which version wrote each word).

Everything the page shows is in the URL, e.g.
`#from=5.2&to=6.2&part=3H&s=3H.27&mode=blame`; also `kind`, `sig`, `q`, `ed`, `sort` and
`rev`, `only` (map), `off` (sweeping edits counted as changes), `step` and `steps`
(panel). Back and Forward step through what you chose. Keys: `/` search, `j`/`k` next and
previous change, Esc close; on the map, the arrow keys move between rows and marks.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and network access to bluetooth.com and
bluetooth.org for the first run.

```sh
uv sync
uv run specdiff extract                  # download and extract every version (~10 min the first time)
uv run specdiff diff                     # compare them (~30 s)
uv run specdiff build                    # render the page into dist/
python3 -m http.server -d dist 8000      # open http://localhost:8000
```

`extract` and `diff` take versions as arguments (`uv run specdiff extract 5.3 5.4`); `diff`
without arguments compares every version extracted, oldest first.

`data/history/` is committed and the site is built from it; `.cache/` and `data/extract/`
stay local. After changing the extraction or the diff, run `extract` and `diff` again and
commit `data/history/`.

```sh
uv run pytest                            # unit tests and checks on the real history
uv run ruff check . && uv run ty check src/
```

## How it works

| Step | Code | Output |
|---|---|---|
| Download: HTML for 5.4 and later (one page per Part), PDF for 5.3 and older | `sources.py` | `.cache/html/`, `.cache/pdf/` (≈ 370 MB) |
| Extract each version into Parts, sections and blocks (paragraph, list item, note, table row, figure title, code) | `html.py`, `pdf.py`, `model.py` | `data/extract/core-X.Y.json` |
| Follow each section through the versions, align its sentences, diff the changed ones word by word, classify each edit, learn the sweeping edits, carry the blame | `align.py`, `classify.py`, `history.py`, `text.py` | `data/history/` |
| Render the page | `build.py`, `site/` | `dist/` |

`data/history/` holds `index.json` (versions, steps with their sweeping edits, Parts, and
every section's status in every step), `steps/N.json` (the ranked changes of step N, with
the ids of the sentences they touch and the words they hold, for the net counts and the
search, and where each sweeping edit applied) and `parts/KEY.json` (the text, diffs and
blame of one Part, loaded when a section of it is opened; a Part over 2 MB is split into
`KEY-0.json`, `KEY-1.json`, …).

Running `extract` again reads the downloads in `.cache/` (about 30 s for the HTML
versions); only `--refresh` downloads again.

PDF extraction uses the PDF's outline for the sections and PyMuPDF for the text. It
drops the running header and footer and the text inside figures (set in other fonts). It
rebuilds tables from the rectangles drawn for their cells, and removes line-end hyphens
only where the PDF writes the word whole somewhere else. Before comparing, the PDF's page
references ("on page 1333") and sheet counts ("(Sheet 4 of 11)") are dropped and
identifiers broken after an underscore are joined. HTML extraction keeps the paragraphs of
a table cell apart (as ` ¶ `), so such rows are compared line by line.

## Adding a version

Add it to `VERSIONS` in `src/specdiff/sources.py`, oldest first. A PDF version needs its
`doc_id`, from the "Core Specification X.Y PDF" link on
`https://www.bluetooth.com/specifications/specs/core-specification-X-Y/`. Then run
`extract`, `diff` and `build` again, and commit `data/history/`.

## Hosting on GitHub Pages

`.github/workflows/pages.yml` lints, tests, builds and deploys on every push to
`main`. It only runs `build`, from the committed `data/history/`. To turn it on, open the
repository's **Settings → Pages** and set the source to **GitHub Actions**.

