#!/usr/bin/env python3
"""
epub2md.py — Convert an EPUB into agent-ready Markdown using pandoc.

Instead of converting the whole book in one pass and guessing at chapter
boundaries from headings, this walks the EPUB spine (the ordered list of
XHTML files inside the archive) and converts each spine item individually.
Chapter boundaries come for free and titles are pulled from the EPUB's own
table of contents when available.

Output:
    <book-slug>/
    ├── INDEX.md           table of contents + stats per chapter
    └── chapters/
        ├── 01-<slug>.md
        ├── 02-<slug>.md
        └── ...

Usage:
    python3 epub2md.py book.epub [-o outdir] [--min-words 30] [--split-level 1]

Requires: pandoc on PATH. Stdlib only otherwise.
"""

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}

# ---------------------------------------------------------------- utilities

def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "untitled"


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def est_tokens(text: str) -> int:
    # ~4 chars per token is a decent English-prose estimate
    return len(text) // 4


# ------------------------------------------------------------- epub parsing

def find_opf(root: Path) -> Path:
    container = root / "META-INF" / "container.xml"
    if not container.exists():
        die("not a valid EPUB: META-INF/container.xml missing")
    tree = ET.parse(container)
    rootfile = tree.find(".//container:rootfile", NS)
    if rootfile is None or "full-path" not in rootfile.attrib:
        die("could not locate OPF package file")
    return root / rootfile.attrib["full-path"]


def parse_opf(opf_path: Path):
    """Return (book_title, ordered list of spine XHTML paths, nav/ncx path)."""
    tree = ET.parse(opf_path)
    base = opf_path.parent

    title_el = tree.find(".//dc:title", NS)
    title = (title_el.text or "").strip() if title_el is not None else ""

    manifest = {}   # id -> (path, media-type, properties)
    for item in tree.findall(".//opf:manifest/opf:item", NS):
        href = unquote(item.attrib.get("href", ""))
        manifest[item.attrib["id"]] = (
            (base / href).resolve(),
            item.attrib.get("media-type", ""),
            item.attrib.get("properties", ""),
        )

    spine = []
    for itemref in tree.findall(".//opf:spine/opf:itemref", NS):
        entry = manifest.get(itemref.attrib.get("idref"))
        if entry and "html" in entry[1]:
            spine.append(entry[0])

    # locate a nav document: EPUB3 nav.xhtml or EPUB2 toc.ncx
    nav = next((p for p, _, props in manifest.values() if "nav" in props), None)
    if nav is None:
        ncx_id = tree.find(".//opf:spine", NS)
        ncx_id = ncx_id.attrib.get("toc") if ncx_id is not None else None
        if ncx_id and ncx_id in manifest:
            nav = manifest[ncx_id][0]
    return title or "book", spine, nav


def parse_toc(nav_path: Path | None) -> dict[str, str]:
    """Map spine filename -> human title, from nav.xhtml or toc.ncx."""
    titles: dict[str, str] = {}
    if nav_path is None or not nav_path.exists():
        return titles
    try:
        tree = ET.parse(nav_path)
    except ET.ParseError:
        return titles

    def register(href: str, label: str) -> None:
        fname = Path(unquote(urlparse(href).path)).name
        label = html.unescape(" ".join(label.split()))
        if fname and label:
            titles.setdefault(fname, label)  # keep first (usually chapter-level)

    if nav_path.suffix == ".ncx":
        for np in tree.findall(".//ncx:navPoint", NS):
            lab = np.find("ncx:navLabel/ncx:text", NS)
            src = np.find("ncx:content", NS)
            if lab is not None and src is not None:
                register(src.attrib.get("src", ""), lab.text or "")
    else:
        for a in tree.findall(".//xhtml:a", NS):
            register(a.attrib.get("href", ""), "".join(a.itertext()))
    return titles


# ---------------------------------------------------------- pandoc + cleanup

CLEANUP_PATTERNS = [
    (re.compile(r"^:{3,}.*$", re.M), ""),                    # ::: div fences
    (re.compile(r"`[^`]*`\{=html\}"), ""),                   # raw html spans
    (re.compile(r"\[\]\{[^}]*\}"), ""),                      # empty anchors []{#x}
    (re.compile(r"\{#[^}]*\}"), ""),                         # heading ids {#x .y}
    (re.compile(r"\{\.[^}]*\}"), ""),                        # attribute blocks {.x}
    (re.compile(r"\[([^\]]+)\]\{[^}]*\}"), r"\1"),           # [text]{.class} spans
    (re.compile(r"\[([^\]]*)\]\((?:[^)#]*\.x?html)?#[^)]*\)"), r"\1"),  # internal links
    (re.compile(r"\n{3,}"), "\n\n"),                         # collapse blank runs
]


def convert_xhtml(path: Path) -> str:
    result = subprocess.run(
        ["pandoc", str(path), "-f", "html", "-t", "gfm-raw_html",
         "--wrap=none", "--markdown-headings=atx"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  warning: pandoc failed on {path.name}: "
              f"{result.stderr.strip().splitlines()[-1] if result.stderr else '?'}",
              file=sys.stderr)
        return ""
    md = result.stdout
    for pattern, repl in CLEANUP_PATTERNS:
        md = pattern.sub(repl, md)
    return md.strip()


JUNK_NAMES = re.compile(
    r"(cover|toc|nav|contents|copyright|colophon|title[-_]?page|halftitle|"
    r"frontmatter|dedication|index|advert|also[-_]?by|about[-_]?the[-_]?author)",
    re.I,
)


def first_heading(md: str) -> str | None:
    m = re.search(r"^#{1,3}\s+(.+)$", md, re.M)
    return " ".join(m.group(1).split()) if m else None


def excerpt(md: str, limit: int = 160) -> str:
    for line in md.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("!["):
            return (line[:limit] + "…") if len(line) > limit else line
    return ""


# ----------------------------------------------------------------- pipeline

def main() -> None:
    ap = argparse.ArgumentParser(description="Convert EPUB to agent-ready Markdown")
    ap.add_argument("epub", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, default=None,
                    help="output directory (default: ./<book-slug>)")
    ap.add_argument("--min-words", type=int, default=30,
                    help="drop spine items shorter than this (default 30)")
    ap.add_argument("--keep-junk", action="store_true",
                    help="keep cover/toc/copyright/index pages")
    args = ap.parse_args()

    if not args.epub.exists():
        die(f"file not found: {args.epub}")
    if shutil.which("pandoc") is None:
        die("pandoc not found on PATH")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            with zipfile.ZipFile(args.epub) as zf:
                zf.extractall(root)
        except zipfile.BadZipFile:
            die("not a valid EPUB (bad zip). DRM-protected files cannot be read.")

        title, spine, nav = parse_opf(find_opf(root))
        toc_titles = parse_toc(nav)
        if not spine:
            die("no readable XHTML content found in spine")

        book_slug = slugify(title)
        outdir = args.outdir or Path.cwd() / book_slug
        chapters_dir = outdir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        print(f"Converting: {title}")
        print(f"Spine items: {len(spine)}\n")

        chapters = []   # (filename, title, words, tokens, excerpt)
        skipped = []
        n = 0
        for item in spine:
            md = convert_xhtml(item)
            words = word_count(md)
            ch_title = toc_titles.get(item.name) or first_heading(md) or item.stem

            is_junk = bool(JUNK_NAMES.search(item.name)) or \
                      bool(JUNK_NAMES.search(ch_title))
            if not args.keep_junk and (words < args.min_words or is_junk):
                skipped.append((item.name, ch_title, words))
                continue

            n += 1
            fname = f"{n:02d}-{slugify(ch_title)}.md"
            body = md if md.startswith("#") else f"# {ch_title}\n\n{md}"
            (chapters_dir / fname).write_text(body + "\n", encoding="utf-8")
            chapters.append((fname, ch_title, words, est_tokens(md), excerpt(md)))
            print(f"  [{n:02d}] {ch_title}  ({words:,} words)")

        if skipped:
            print(f"\nSkipped {len(skipped)} items "
                  f"(front/back matter or < {args.min_words} words):")
            for name, t, w in skipped:
                print(f"  - {name}  ({t}, {w} words)")

        total_words = sum(c[2] for c in chapters)
        total_tokens = sum(c[3] for c in chapters)

        index = [f"# {title}", "",
                 f"Chapters: {len(chapters)} · Words: {total_words:,} · "
                 f"Est. tokens: ~{total_tokens:,}", "",
                 "| # | Chapter | File | Words | ~Tokens |",
                 "|---|---------|------|-------|---------|"]
        for i, (fname, t, w, tok, _) in enumerate(chapters, 1):
            index.append(f"| {i} | {t} | `chapters/{fname}` | {w:,} | {tok:,} |")
        index += ["", "## Chapter notes", ""]
        for fname, t, w, tok, exc in chapters:
            index.append(f"### {t}")
            index.append(f"*File: `chapters/{fname}`*")
            if exc:
                index.append(f"\n> {exc}")
            index.append("\n<!-- TODO: add a 1-2 sentence summary -->\n")
        (outdir / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")

        print(f"\nDone → {outdir}/")
        print(f"Total: {total_words:,} words, ~{total_tokens:,} tokens")
        if total_tokens < 150_000:
            print("Fits in a single context window — you could also merge into one file.")
        else:
            print("Too large for one context window — use INDEX.md + per-chapter loading.")


if __name__ == "__main__":
    main()
