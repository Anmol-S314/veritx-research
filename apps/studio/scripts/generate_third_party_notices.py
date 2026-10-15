#!/usr/bin/env python3
"""Generate notices for production npm packages in this web Studio lockfile.

This intentionally does not claim coverage for desktop shells, external tools,
container/base OS packages, fonts outside npm, or other release artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "package-lock.json"
NODE_MODULES = ROOT / "node_modules"
OUTPUT = ROOT / "public" / "THIRD_PARTY_NOTICES.md"
REPO_LICENSE = ROOT.parent.parent / "LICENSE"
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "COPYING")
FONT_ASSETS = (
    ("Inter variable webfont", "fonts/inter-var.woff2", "OFL-1.1", "licenses/inter-OFL-1.1.txt"),
    ("JetBrains Mono variable webfont", "fonts/jetbrains-mono-var.woff2", "OFL-1.1", "licenses/jetbrains-mono-OFL-1.1.txt"),
)


def main() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    packages: list[tuple[str, str, str, str]] = []
    for location, record in lock.get("packages", {}).items():
        if not location.startswith("node_modules/") or record.get("dev", False):
            continue
        name = location.removeprefix("node_modules/")
        version = record.get("version")
        license_id = record.get("license")
        if not version or not license_id:
            raise SystemExit(f"missing locked version/license: {location}")
        package_dir = NODE_MODULES / location.removeprefix("node_modules/")
        manifest = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
        if manifest.get("version") != version:
            raise SystemExit(f"installed version differs from lock: {name} {version}")
        if manifest.get("license") != license_id:
            raise SystemExit(f"installed license differs from lock: {name} {license_id}")
        license_file = next((package_dir / candidate for candidate in LICENSE_NAMES
                             if (package_dir / candidate).is_file()), None)
        if license_file is None:
            raise SystemExit(f"license text file missing: {name} {version} ({license_id})")
        text = license_file.read_text(encoding="utf-8").strip()
        if not text:
            raise SystemExit(f"empty license text: {name} {version}")
        packages.append((name, version, license_id, text))

    if not packages:
        raise SystemExit("no production npm packages found")
    packages.sort(key=lambda item: item[0].casefold())
    out = [
        "# Third-party notices — VeritX Studio web UI",
        "",
        "Generated from the locked production npm dependency tree, the two self-hosted font license files, and the repository license. It covers this web UI and the included font/image assets only; it does not cover Tauri/desktop runtimes, engine binaries, OS/container packages, or other release artifacts. Regenerate and independently review for every release candidate.",
        "",
        "## Package inventory",
        "",
        "| Package | Version | Declared license |",
        "|---|---:|---|",
    ]
    for name, version, license_id, _ in packages:
        out.append(f"| `{name}` | `{version}` | {license_id} |")

    out += ["", "## Embedded fonts and project artwork", "",
            "| Asset | File | Declared license |",
            "|---|---|---|"]
    license_texts: dict[str, list[str]] = {}
    for name, version, license_id, text in packages:
        license_texts.setdefault(text, []).append(f"`{name}@{version}`")
    for title, filename, license_id, license_path in FONT_ASSETS:
        asset = ROOT / "public" / filename
        notice = ROOT / "public" / license_path
        if not asset.is_file() or not notice.is_file():
            raise SystemExit(f"missing font asset/license: {filename} / {license_path}")
        out.append(f"| {title} | `{filename}` | {license_id} |")
        license_texts.setdefault(notice.read_text(encoding="utf-8").strip(), []).append(title)
    out.append("| VeritX Studio source and board illustration | `LICENSE` / `assets/veritx-board.webp` | MIT (repository license) |")
    license_texts.setdefault(REPO_LICENSE.read_text(encoding="utf-8").strip(), []).append("VeritX Studio source and board illustration")

    out += ["", "## License texts", ""]
    for text, owners in license_texts.items():
        label = ", ".join(owners)
        out += [f"### {label}", "", "```text", text, "```", ""]
    OUTPUT.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {len(packages)} production packages, {len(license_texts)} distinct license texts and embedded-asset notices")


if __name__ == "__main__":
    main()
