#!/usr/bin/env python3
"""Check that the checked-in web Studio SBOM/notices cover locked production packages/assets."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    expected: dict[str, tuple[str, str]] = {}
    for location, item in lock.get("packages", {}).items():
        if location.startswith("node_modules/") and not item.get("dev", False):
            name = location.removeprefix("node_modules/")
            version, license_id = item.get("version"), item.get("license")
            if not version or not license_id:
                raise SystemExit(f"missing version/license in package lock: {name}")
            expected[name] = (version, license_id)

    notice = (ROOT / "public/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| ([^|]+) \|$", notice, re.M)
    observed = {name: (version.strip(), license_id.strip()) for name, version, license_id in rows}
    if observed != expected:
        raise SystemExit(f"notice package inventory differs from lock; missing={sorted(expected.keys()-observed.keys())}, extra={sorted(observed.keys()-expected.keys())}")
    for name, (version, _) in expected.items():
        if f"`{name}@{version}`" not in notice:
            raise SystemExit(f"no attributable license-text owner for {name}@{version}")

    sbom = json.loads((ROOT / "public/STUDIO_UI_SBOM.cdx.json").read_text(encoding="utf-8"))
    components = sbom.get("components", [])
    sbom_packages: dict[str, tuple[str, str]] = {}
    for component in components:
        purl = component.get("purl", "")
        match = re.fullmatch(r"pkg:npm/(.+)@([^@]+)", unquote(purl))
        if not match:
            raise SystemExit(f"unexpected SBOM component PURL: {purl}")
        name, version = match.groups()
        licenses = component.get("licenses", [])
        license_id = licenses[0].get("license", {}).get("id") if licenses else None
        sbom_packages[name] = (version, license_id)
    if sbom_packages != expected:
        raise SystemExit(f"SBOM package inventory differs from lock; missing={sorted(expected.keys()-sbom_packages.keys())}, extra={sorted(sbom_packages.keys()-expected.keys())}")

    assets = [
        ("fonts/inter-var.woff2", "licenses/inter-OFL-1.1.txt", "Inter variable webfont"),
        ("fonts/jetbrains-mono-var.woff2", "licenses/jetbrains-mono-OFL-1.1.txt", "JetBrains Mono variable webfont"),
    ]
    for asset, license_file, label in assets:
        if not (ROOT / "public" / asset).is_file() or not (ROOT / "public" / license_file).is_file():
            raise SystemExit(f"missing embedded font/license pair: {asset}")
        if not (ROOT / "public" / license_file).read_text(encoding="utf-8").strip():
            raise SystemExit(f"empty embedded font license: {license_file}")
        if f"| {label} | `{asset}` | OFL-1.1 |" not in notice or f"### {label}" not in notice:
            raise SystemExit(f"notice does not attribute embedded asset {label}")
    if not (ROOT / "public/assets/veritx-board.webp").is_file() or "assets/veritx-board.webp" not in notice:
        raise SystemExit("board illustration is missing or unattributed")
    print(f"PASS: {len(expected)} locked production packages match both SBOM and notices; embedded fonts and board artwork have license attribution")
    print("SCOPE: web Studio lockfile and listed public assets only; no desktop/runtime/engine artifacts")

if __name__ == "__main__":
    main()
