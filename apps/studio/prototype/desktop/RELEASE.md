# Srota Studio 0.1.0 — standalone desktop artifacts

Both artifacts are self-contained: they own the gateway, the Python runtime and
all three simulator backends (BookSim, ASTRA/BookSim, Ramulator). No checkout,
Node, Python, toolchain, manually started server, WSL or Docker is needed on the
target machine.

## Artifacts

| Platform | File | Size | SHA-256 |
| --- | --- | --- | --- |
| Linux x86-64 | `Srota Studio_0.1.0_amd64.deb` | 111.34 MiB | `a25a75d51a88530e5c347e3ceecac880093a583c7c71015f995f10271d7be389` |
| Windows x86-64 | `Srota Studio_0.1.0_x64-setup.exe` | 262.6 MiB | `38bd6796c695c36db4ba6fd21d03d543f9d4047cf5dbdd9a84f8b19e83fbff58` |

The Linux package was rebuilt on 2026-10-30 to include the Analysis topology UI
changes (window-matrix granularity, equal-width/equal-height analysis panels,
collapsible reference tables, channel-pick auto-scroll, the zoomable
delay-cost scatter, a fluid router heatmap, the resized playback and measured-
channel detail panels, and the contextual assistant drawer with saved local
model settings). The Windows installer entry above predates that rebuild and
must be rebuilt from the current tree before it is published.

Build paths:

- `apps/studio/prototype/src-tauri/target/release/bundle/deb/`
- `apps/studio/prototype/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`

Re-check a download with `sha256sum <file>` (Linux) or
`Get-FileHash -Algorithm SHA256 <file>` (Windows).

## Supported platforms

Earlier Windows builds shipped a gateway frozen before the ASTRA parser surface
was added to the spec, so that build refused embedded fabric configs. Both
artifacts above were rebuilt after the fix; `desktop/windows/test_installer_wine.sh`
now fails if the installed sidecar cannot load its Ramulator binding or read that
parser surface, so a stale freeze cannot pass again.

| | Verified | Notes |
| --- | --- | --- |
| Linux x86-64, Ubuntu 24.04 | yes | Installed and launched on a clean Ubuntu 24.04 image with no Python/Node. Needs the distro WebKitGTK 4.1 / GTK 3 stack, which the package declares via `Depends:`. |
| Windows 10/11 x86-64 | packaging only | Installer built and installed, and the installed sidecar runs, but not yet on a real Windows machine. WebView2 is bundled (offline installer), so no network is needed. |
| macOS, arm64 | not supported | Not built. |

Linux glibc floor is whatever the build host provides (Ubuntu 24.04, glibc
2.39). Older distributions without WebKitGTK 4.1 are not supported.

## Install

Linux:

```bash
sudo apt install "./Srota Studio_0.1.0_amd64.deb"
srota-studio
```

Windows: run `Srota Studio_0.1.0_x64-setup.exe`. It is a per-user install (no
administrator prompt), lands in `%LOCALAPPDATA%\Srota Studio`, and installs the
bundled WebView2 runtime when the machine does not already have it. Uninstall
through Settings → Apps, or `uninstall.exe` in that folder.

User data lives outside the install directory, so uninstalling or reinstalling
keeps projects and runs. On Linux the package removes its binaries and leaves
`~/.local/share/com.srota.studio` intact; reinstall then picks the data back up.

## What the installers contain

- `srota-studio` / `srota-studio.exe` — Tauri shell.
- `srota-gateway` / `srota-gateway.exe` — frozen gateway: uvicorn/FastAPI app,
  CPython runtime, `booksim`(+`.exe`), `AstraSim_BookSim2`(+`.exe`),
  `_ramulator` native binding (plus `libramulator.dll` on Windows), Chakra
  protobuf schema and the JSON/YAML resources the gateway loads at startup.
- Windows only: `MicrosoftEdgeWebView2RuntimeInstaller.exe` (offline runtime).
- Every simulator binary ships with its `.build-manifest.json` provenance file;
  the gateway refuses a backend whose provenance does not verify.

### What the installers deliberately do NOT contain

The numeric stack — numpy, scipy, scikit-learn, scikit-optimize — is excluded
from both packages (about 32 MiB of an earlier 116 MiB `.deb`). It only ever
backed four topology-synthesis engines, and those engines have no Studio
surface, are undocumented in `PRODUCT-API.md`, are scheduled for removal from
product surfaces by `PRODUCT-FLOWS.md` PF-D15, and in measurement refused every
problem above 9 nodes while never beating the numpy-only engine on objective.

Source and CLI installs still have the stack, so synthesis is unchanged there.
In the packaged app the affected engines refuse with HTTP 503 and code
`ENGINE_UNAVAILABLE`, naming the missing packages; `GET /api/v1/synthesis/engines`
reports `available: false` and `numeric_stack_shipped: false` rather than
silently substituting an engine that still imports. Both build lanes fail if the
stack reappears **or** if the refusal stops being typed, so this cannot drift
back in unnoticed (see `desktop/build_backend.py` and
`desktop/windows/freeze_backend.sh`).

### ASTRA producer (patched HEAD)

`AstraSim_BookSim2` is built from HEAD plus the committed fork patch `c0b41679`,
not from an older pinned revision. Unpatched HEAD refuses every run: BookSim's
`EmbedTM` will not accept injection until `SetHostFlitLimit()` is called and the
HEAD ASTRA wrapper never called it, so the run reported no per-rank results.

The patch adds `--booksim2-host-flit-limit`, forwards it into the fabric
constructor, sets the limit immediately after the traffic manager is created, and
turns a negative capacity prediction at any injection site into a named refusal
(exit code 3) instead of a silent drop. This backend records the value in the
machine projection and passes it on the runtime command, asserting its presence.

The value is the fabric's total host-side flit capacity, configured as an
uncapped injection window (`1 << 40`); a buffer-derived ceiling was tried and
falsely refused real 8192-flit streams. `VERITX_HOST_FLIT_LIMIT` overrides it for
qualification work.

Reproducible with `desktop/build_astra_linux.sh` (Linux, builds in a clean git
worktree) and `desktop/windows/build_astra.sh` with `SOURCE_REPO=<worktree>`
(Windows, committed snapshot). Both manifests report `source_dirty=false`,
Linux `source_revision=c0b41679` SHA-256 `c190d6aa…`, Windows
`AstraSim_BookSim2.exe` SHA-256 `28cfd139…`.

Verified over all 28 shipped presets: `ASTRA2_EMBEDDED_BOOKSIM` completes 24
presets, including the three native-routing presets
(`ring_native64`, `tree4_native64`, `fly_native64`) that the previous release
could only run on `BOOKSIM_STANDALONE`. The four remaining presets are the
schema-version-2 refusals documented in `ACCEPTANCE.md`, not producer failures.

Measured makespans (`SYSTEM_MAKESPAN`, cycles) for the presets that changed or
that anchor the comparison — previous v1 producer, current Linux package, current
Windows package:

| Preset | v1 `3d47fbb8` | this release, Linux | this release, Windows |
| --- | --- | --- | --- |
| `flatfly16` | 4659 | 4659 | 4659 |
| `torus25` | 5205 | 5205 | 5205 |
| `fattree16` | 4509 | 4509 | 4509 |
| `ring_native64` | not completed | 4798 | 4798 |
| `tree4_native64` | not completed | 8313 | 8313 |
| `fly_native64` | not completed | 14855 | 14855 |

Result stability was measured, not assumed: the 21 presets that also completed
on the previous (v1 `3d47fbb8`) producer give identical makespans — 0 changed —
and the Windows package reproduces the Linux makespans on all 24 completed
presets. The three native presets have no previous value: that producer never
completed them.

## Third-party components and licensing

The application is MIT (see `LICENSE`). Bundled third-party components:

| Component | Version / source | License evidence |
| --- | --- | --- |
| Tauri, tao, wry | 2.x / 0.37 / 0.5x (crates.io) | MIT or Apache-2.0 per crate metadata |
| WebView2 Runtime (Windows) | Microsoft redistributable | Microsoft terms; bundled offline installer |
| CPython (Windows build) | 3.14.0 (python.org embeddable) | PSF-2.0 (`LICENSE.txt` in the distribution) |
| PyInstaller | 6.20.0 | GPL-2.0 with the bootloader exception |
| FastAPI / Starlette / Uvicorn | 0.x | MIT / BSD-3-Clause / BSD-3-Clause |
| pydantic / pydantic-core | 2.x | MIT |
| protobuf (Python + C++) | 3.21.12 C++, 7.x Python | BSD-3-Clause |
| PyYAML | 6.x | MIT |
| nanobind | vendored `third_party/ramulator2/ext/nanobind` | BSD-3-Clause (`LICENSE` present) |
| yaml-cpp, fmt | vendored under `third_party/ramulator2/ext` | MIT (`LICENSE` present) |
| BookSim2 | vendored `third_party/booksim2` | UNVERIFIED — no license file in the vendored tree |
| ASTRA-sim | `518bd51` (see `third_party/astra-sim/METADATA.json`) | UNVERIFIED — no license file in the vendored tree |
| Chakra | vendored under `third_party/astra-sim/.../chakra` | Apache-2.0 (`LICENSE.md` present) |
| Ramulator2 | vendored `third_party/ramulator2` | UNVERIFIED — no license file in the vendored tree |

Rows marked UNVERIFIED need the upstream license confirmed and a license file
added to the vendored tree before redistribution outside this project. The
installer does not currently show a license page.

numpy, scipy, scikit-learn, joblib, threadpoolctl and scikit-optimize are build
host dependencies only — no longer bundled, so they add no redistribution
obligation to the shipped artifacts.

## Reproducing the builds

Linux:

```bash
npm --prefix apps/studio/prototype run desktop:build      # deb
bash apps/studio/prototype/desktop/test_clean_linux.sh    # clean install + gateway tests
bash apps/studio/prototype/desktop/test_linux_reinstall.sh
bash apps/studio/prototype/desktop/test_clean_linux_ui.sh
```

Windows (cross-built on Linux; Wine is used only to execute Windows binaries,
never as platform acceptance evidence):

```bash
bash apps/studio/prototype/desktop/windows/build_booksim.sh
bash apps/studio/prototype/desktop/windows/build_astra.sh
bash apps/studio/prototype/desktop/windows/build_ramulator.sh
bash apps/studio/prototype/desktop/windows/build_ramulator_binding.sh
bash apps/studio/prototype/desktop/windows/freeze_backend.sh
bash apps/studio/prototype/desktop/windows/build_shell.sh
bash apps/studio/prototype/desktop/windows/test_gateway_windows.sh
bash apps/studio/prototype/desktop/windows/test_installer_wine.sh
```

Gate status and every piece of evidence, including what is still unproven, is
tracked in `ACCEPTANCE.md`.
