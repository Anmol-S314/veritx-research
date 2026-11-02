# Srota Studio desktop (Linux and Windows)

The Tauri 2 application uses **this prototype**, not a copied frontend.
`desktop:dev` starts the existing Vite server, opens its UI in Tauri, and starts
the Python gateway automatically. React/CSS edits hot-reload in that window.
Restart desktop development after backend edits. Installed applications use a
snapshot: rebuild/reinstall to pick up changes; no updater is included.

Build hosts: Linux x86-64 and Windows x86-64. macOS is not supported.
Verification status lives in [ACCEPTANCE.md](ACCEPTANCE.md) and
[RELEASE.md](RELEASE.md); read them before claiming a platform works.

## Prerequisites

On Ubuntu/Debian, install Tauri's development prerequisites once:

```bash
sudo apt update
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file \
  libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

Rust/Cargo and Node/npm are also required to **build**, not to use an installed
application. On Windows, install the Tauri prerequisites (WebView2 build
dependencies, MSVC build tools) and build from a Developer PowerShell; the
Windows bundle is produced from `src-tauri/tauri.windows.conf.json` (NSIS,
per-user, offline WebView2). Windows-specific process control lives in
`veritx_dse/core/windows_job.py` and `core/file_lock.py`, so the gateway no
longer depends on POSIX-only primitives.

Install the existing Studio dependencies and the small desktop dependencies
from the repository root:

```bash
npm --prefix apps/studio ci
npm --prefix apps/studio/prototype ci
```

### Python build environment

Use an isolated environment to avoid accidentally bundling optional ML/GPU
packages from the host. The interpreter must match the built Ramulator extension:
the current checkout has `_ramulator.cpython-314-x86_64-linux-gnu.so`, so use
Python 3.14 (or rebuild Ramulator for another Python first).

From the repository root, with [uv](https://docs.astral.sh/uv/) installed:

```bash
uv venv --python /usr/bin/python3.14 apps/studio/prototype/.desktop-venv
uv pip install --python apps/studio/prototype/.desktop-venv/bin/python \
  -r apps/studio/prototype/desktop/requirements-build.txt
uv pip install --python apps/studio/prototype/.desktop-venv/bin/python --no-deps \
  ./third_party/astra-sim/extern/graph_frontend/chakra
```

Only Chakra's protobuf emission utilities are used; its optional PyTorch
conversion stack is deliberately not installed. Source code is loaded directly
from this checkout in development. `SROTA_PYTHON` can override the interpreter.

Build the repository's BookSim, ASTRA/BookSim and matching Ramulator binaries
first if absent. Packaging refuses missing binaries or build manifests instead
of silently distributing non-working simulator controls. Existing binaries in
this checkout are reused, not rebuilt or modified.

## Develop

From the repository root:

```bash
npm --prefix apps/studio/prototype run desktop:dev
```

Do not start another Vite instance on port 5174 first; Tauri owns that server.
Browser-only development (`npm --prefix apps/studio/prototype run dev`) still
works exactly as before with the existing `/gw` proxy and separate gateway.

Desktop startup waits for the real gateway's readiness announcement before the
UI imports its gateway client. With no project selected, desktop shows the live
project chooser, not the illustrative browser sample. An empty store is not an
offline backend; create or select a real project to open the workspace. HTTP, event streams and artifact downloads all
use that same backend. A failure is not converted into a successful fixture
connection.

## Build and test

```bash
npm --prefix apps/studio/prototype run desktop:test
npm --prefix apps/studio/prototype test
npm --prefix apps/studio/prototype run build
npm --prefix apps/studio/prototype run backend:build
SROTA_SIDECAR="$PWD/apps/studio/prototype/src-tauri/binaries/gateway/srota-gateway" \
  npm --prefix apps/studio/prototype run desktop:test
npm --prefix apps/studio/prototype run desktop:build
```

The final command freezes the gateway, builds the **same** frontend, builds
Tauri, and creates a Debian package under
`apps/studio/prototype/src-tauri/target/release/bundle/deb/`.
The target suffix above is for this x86-64 Linux machine; the backend build
script derives the local Rust host triple.

The gateway is frozen as a one-dir tree (`src-tauri/binaries/gateway/`), not a
one-file archive, and Tauri ships it as an app resource. A one-file archive
re-extracts roughly 250 MB on every launch; a one-dir tree is installed once
and launched in place. The installed size is therefore larger while the
compressed `.deb` stays about the same.

The installer includes the gateway's Python runtime, runtime registries,
qualification evidence, simulator binaries and manifests, Chakra protobuf
bindings, and Ramulator's matching native extension/shared-library dependencies.
End users do not need to install Python or run a server. Tauri/WebKit and libc
remain system dependencies; this is not a universal static Linux executable.
Build on the oldest Linux distribution you intend to support.

Tests exercise a real process from an unrelated working directory using a fresh
temporary data directory. They cover unauthenticated rejection, CORS/host checks,
catalogs, compile/evaluate/artifacts, SSE, persistence/restart, Python workers,
native Python bindings, and shutdown on parent-pipe closure.

## Ownership and security

- Only `127.0.0.1` is bound, using a socket assigned by the OS (no fixed-port race).
- Every launch gets a fresh, unguessable URL capability. It is passed through
  local Tauri IPC, not stored in frontend source or logged in HTTP access logs.
  URL capabilities support EventSource and downloads without insecure public
  endpoints. Treat that URL as a secret.
- Only the local Tauri origins and the fixed Vite development origin receive
  CORS access; host validation also rejects DNS-rebinding hostnames.
- JavaScript gets no shell/filesystem plugin. The only application command
  returns this instance's gateway connection.
- The existing backend still owns validation, jobs, cancellation and evidence.
- Closing Tauri closes/signals its owned sidecar. The backend also observes a
  parent pipe so a desktop crash triggers gateway shutdown.

By default, data and logs live under
`${XDG_DATA_HOME:-~/.local/share}/com.srota.studio/`:
`projects/`, `runs/`, `store/`, `revisions/`, and `backend.log`.
No existing repository project/run is copied, deleted or overwritten.
Browser localStorage and Tauri localStorage are separate; browser-only local
prototype edits do not automatically migrate to the desktop store.

## Boundaries

This is a local prototype distribution, not a signed public release. The
LLMServingSim optional serving stack, pre-generated reports, provider credentials,
and existing user runs are not bundled. Capabilities which require unavailable
optional resources must continue reporting that absence. AI/provider access
still requires explicit configuration and approval; no credentials are packaged.
Review the complete desktop/native/Python license inventory before external
redistribution; the parent's web-only notices do not cover this artifact.

No auto-updater, Python-to-Rust rewrite, custom titlebar, or migration of existing
browser/backend data is included. The frontend and backend are not forks.

References:
- https://v2.tauri.app/start/prerequisites/
- https://v2.tauri.app/develop/sidecar/
- https://pyinstaller.org/en/stable/
