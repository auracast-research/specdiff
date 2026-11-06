"""Which Core versions there are, where the SIG publishes them and how to fetch them.

Core 5.4 and later are published as HTML, one page per Part; Core 5.3 and older as one
PDF each. Both are cached under .cache/ and never re-downloaded unless asked to."""

import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR = Path(".cache")
USER_AGENT = "specdiff/0.1 (Bluetooth Core Specification diff)"

HTML_ROOT = "https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML"
PDF_URL = "https://www.bluetooth.org/docman/handlers/downloaddoc.ashx?doc_id={doc_id}"


@dataclass(frozen=True)
class Version:
    label: str  # "5.3"
    pdf_doc_id: int | None = None  # set for versions published only as PDF
    date: str = ""  # month of adoption, for the timeline

    @property
    def is_pdf(self) -> bool:
        return self.pdf_doc_id is not None


# Oldest first. The doc ids are the "Core Specification X.Y PDF" links on
# https://www.bluetooth.com/specifications/specs/core-specification-X-Y/
VERSIONS = [
    Version("4.2", pdf_doc_id=441541, date="2014-12"),
    Version("5.0", pdf_doc_id=421043, date="2016-12"),
    Version("5.1", pdf_doc_id=457080, date="2019-01"),
    Version("5.2", pdf_doc_id=478726, date="2019-12"),
    Version("5.3", pdf_doc_id=521059, date="2021-07"),
    Version("5.4", date="2023-01"),
    Version("6.0", date="2024-08"),
    Version("6.1", date="2025-05"),
    Version("6.2", date="2025-11"),
    Version("6.3", date="2026-05"),
    Version("7.0", date="2026-11"),
]
BY_LABEL = {version.label: version for version in VERSIONS}


def version(label: str) -> Version:
    if label not in BY_LABEL:
        msg = f"unknown Core version {label!r}; known: {', '.join(BY_LABEL)}"
        raise KeyError(msg)
    return BY_LABEL[label]


# HTML


def index_urls(label: str) -> list[str]:
    """Where the index page of an HTML version may be: its folder is "Core_v6.3" from 6.3
    on, "Core-62" before."""
    folders = [f"Core_v{label}", f"Core-{label.replace('.', '')}"]
    return [f"{HTML_ROOT}/{folder}/out/en/index-en.html" for folder in folders]


def html_dir(label: str) -> Path:
    return CACHE_DIR / "html" / f"core-{label}"


def fetch_index(label: str, *, refresh: bool = False) -> tuple[str, Path]:
    """URL and cached copy of the index page of an HTML version."""
    folder = html_dir(label)
    url_file = folder / "index.url"
    path = folder / "index.html"
    if path.exists() and url_file.exists() and not refresh:
        return url_file.read_text(encoding="utf-8").strip(), path
    for url in index_urls(label):
        try:
            body = _get(url)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        _write(path, body)
        _write(url_file, url.encode())
        return url, path
    msg = f"Core {label} is not published as HTML"
    raise LookupError(msg)


def fetch_part(label: str, index_url: str, href: str, *, refresh: bool = False) -> Path:
    """Cached copy of one Part page, `href` relative to the index page."""
    path = html_dir(label) / "parts" / _safe_name(href)
    if path.exists() and not refresh:
        return path
    url = urllib.parse.urljoin(index_url, href)
    print(f"fetching Core {label}: {url}", file=sys.stderr)
    _write(path, _get(url))
    return path


def part_url(index_url: str, href: str) -> str:
    return urllib.parse.urljoin(index_url, href)


def _safe_name(href: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", href)


# PDF


def pdf_path(label: str) -> Path:
    return CACHE_DIR / "pdf" / f"core-{label}.pdf"


def pdf_url(label: str) -> str:
    doc_id = version(label).pdf_doc_id
    if doc_id is None:
        msg = f"Core {label} is published as HTML, not as PDF"
        raise ValueError(msg)
    return PDF_URL.format(doc_id=doc_id)


def fetch_pdf(label: str, *, refresh: bool = False) -> Path:
    path = pdf_path(label)
    if path.exists() and not refresh:
        return path
    url = pdf_url(label)
    print(f"fetching Core {label}: {url}", file=sys.stderr)
    body = _get(url)
    if not body.startswith(b"%PDF"):
        msg = f"{url} did not return a PDF"
        raise ValueError(msg)
    _write(path, body)
    return path


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
