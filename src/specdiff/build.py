"""Render the site into dist/: the page, its script and styles, and data/history/ copied
to dist/data/, which the page loads as it needs it."""

import hashlib
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

SITE_DIR = Path("site")
HISTORY_DIR = Path("data/history")


def build(out: Path) -> int:
    index_path = HISTORY_DIR / "index.json"
    if not index_path.exists():
        print("no data/history/index.json: run specdiff extract, then specdiff diff")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_DIR / "static", out)
    shutil.copytree(HISTORY_DIR, out / "data")

    versions = index["versions"]
    volumes: dict[int, list[dict]] = {}
    for part in index["parts"]:
        title = next(t for t in reversed(part["titles"]) if t)
        volumes.setdefault(part["vol"], []).append({"key": part["key"], "title": title})
    env = Environment(
        loader=FileSystemLoader(SITE_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["asset"] = lambda name: f"{name}?v={_digest(out / name)}"
    page = env.get_template("index.html.j2").render(
        versions=versions,
        first=versions[0]["label"],
        last=versions[-1]["label"],
        volumes=sorted(volumes.items()),
        sections=len(index["sections"]),
        data_version=_digest(index_path),
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    print(
        f"built {out}/ with {len(versions)} versions ({versions[0]['label']} to"
        f" {versions[-1]['label']}) and {len(index['sections'])} sections"
    )
    return 0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
