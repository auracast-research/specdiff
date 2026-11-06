"""Command line entry point: specdiff extract | diff | build."""

import argparse
import sys
from pathlib import Path

from specdiff import sources

DATA_DIR = Path("data")


def extract_path(label: str) -> Path:
    return DATA_DIR / "extract" / f"core-{label}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="specdiff", description="Diff the Bluetooth Core Specification across versions."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    labels = [version.label for version in sources.VERSIONS]

    extract = commands.add_parser(
        "extract", help="download versions and extract their text into data/extract/"
    )
    extract.add_argument("versions", nargs="*", default=labels)
    extract.add_argument("--refresh", action="store_true", help="download the spec again")

    diff = commands.add_parser(
        "diff", help="compare the extracted versions, oldest first, into data/history/"
    )
    diff.add_argument("versions", nargs="*", help="default: every version extracted")

    site = commands.add_parser("build", help="render the site into dist/")
    site.add_argument("--out", type=Path, default=Path("dist"))

    args = parser.parse_args(argv)
    if args.command == "extract":
        return _extract(args.versions, refresh=args.refresh)
    if args.command == "diff":
        return _diff(args.versions or [v.label for v in sources.VERSIONS])
    if args.command == "build":
        from specdiff.build import build

        return build(args.out)
    return 1


def _extract(labels: list[str], *, refresh: bool) -> int:
    from specdiff import html, pdf

    for label in labels:
        version = sources.version(label)
        module = pdf if version.is_pdf else html
        spec = module.extract(label, refresh=refresh)
        spec.save(extract_path(label))
        sections = sum(len(part.sections) for part in spec.parts)
        blocks = sum(len(section.blocks) for part in spec.parts for section in part.sections)
        print(
            f"Core {label}: {len(spec.parts)} Parts, {sections} sections, {blocks} blocks"
            f" -> {extract_path(label)}"
        )
    return 0


def _diff(labels: list[str]) -> int:
    from specdiff.history import History
    from specdiff.model import Spec

    order = [v.label for v in sources.VERSIONS]
    labels = sorted((label for label in labels if extract_path(label).exists()), key=order.index)
    if len(labels) < 2:
        print("extract at least two versions first: specdiff extract", file=sys.stderr)
        return 1
    history = History([Spec.load(extract_path(label)) for label in labels])
    history.run()
    history.write(DATA_DIR / "history")
    for summary, rules in zip(
        (history.step_summary(n) for n in range(len(history.steps))), history.rules, strict=True
    ):
        a, b = labels[summary["from"]], labels[summary["to"]]
        sections = summary["sections"]
        print(
            f"{a} -> {b}: {sections['changed']} sections changed, {sections['added']} added,"
            f" {sections['removed']} removed, {sections['editorial']} editorial only;"
            f" {len(rules)} sweeping rewrites"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
