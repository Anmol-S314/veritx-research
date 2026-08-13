#!/usr/bin/env python3
"""Validate the front-facing site in site/.

Checks, with no dependencies beyond the stdlib:
  * every page is well-formed enough to parse with html.parser
  * every internal href/src (page links, anchors, assets) resolves
  * no absolute links to private infrastructure (internal registry etc.)
  * every page has <title> and the meta description

Usage: python3 scripts/check_site.py [site_dir]
Exit code 0 = clean. Run in CI after every change to site/.
"""
import pathlib
import re
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "site")
PRIVATE_HOSTS = re.compile(
    r"internal-devrepo\.|gitlab\.|ghcr\.io|localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+"
)


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.title = None
        self.meta_desc = False
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("a", "link"):
            href = d.get("href")
            if href:
                self.links.append(href)
        elif tag == "img" and d.get("src"):
            self.links.append(d["src"])
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and d.get("name") == "description":
            self.meta_desc = bool(d.get("content"))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data


def resolve(base: pathlib.Path, href: str) -> pathlib.Path | None:
    if href.startswith(("http://", "https://", "mailto:", "#", "tel:")):
        return None
    path = href.split("#")[0]
    return (base.parent / path).resolve()


def main() -> int:
    errors = []
    pages = sorted(ROOT.glob("*.html"))
    if not pages:
        print(f"ERROR: no HTML pages found in {ROOT}")
        return 1

    by_name = {p.resolve(): p for p in pages}

    for page in pages:
        rel = page.relative_to(ROOT)
        try:
            raw = page.read_text()
        except OSError as e:
            errors.append(f"{rel}: unreadable: {e}")
            continue

        if PRIVATE_HOSTS.search(raw):
            errors.append(f"{rel}: contains a private/internal URL")

        p = LinkExtractor()
        try:
            p.feed(raw)
        except Exception as e:
            errors.append(f"{rel}: parse error: {e}")
            continue

        if not p.title or not p.title.strip():
            errors.append(f"{rel}: missing <title>")
        if not p.meta_desc:
            errors.append(f"{rel}: missing meta description")

        for href in p.links:
            target = resolve(page, href)
            if target is None:
                continue
            if target.suffix == ".html":
                if target not in by_name:
                    errors.append(f"{rel}: broken link -> {href}")
            elif not target.exists():
                errors.append(f"{rel}: broken asset link -> {href}")

    if errors:
        print(f"FAIL: {len(errors)} issue(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {len(pages)} pages, all links/assets/titles/descriptions resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
