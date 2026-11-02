# Windows build lane — in progress, NOT a release

Acceptance is owned by `../ACCEPTANCE.md`. No Windows installer or native
Windows acceptance is claimed yet.

## Packaging contract

`src-tauri/tauri.windows.conf.json` selects an NSIS setup executable, per-user
installation and the offline WebView2 installer. Unlike the Linux default,
its before-build command only builds the frontend: it must not freeze a Linux
gateway while cross-compiling the Windows shell.

A real Windows sidecar must already exist at
`src-tauri/binaries/srota-gateway-x86_64-pc-windows-msvc.exe`.
`desktop/build_backend.py` can name native Windows freezer output correctly;
it still requires Windows simulator executables, manifests and the matching
Ramulator `.pyd`. Do not substitute renamed Linux binaries or dummy sidecars.

The Tauri launcher selects Windows Python development paths and `.exe` release
paths, and launches the gateway without an extra console. Windows worker
containment and simulator parity remain outstanding.

## Linux-hosted build tools

```bash
podman build -t localhost/srota-windows-tools:acceptance \
  apps/studio/prototype/desktop/windows
bash apps/studio/prototype/desktop/windows/build_booksim.sh
```

The BookSim script mounts sources read-only, compiles a temporary copy, and
writes under `apps/studio/prototype/.desktop-build/windows/`. It cannot modify
the working Linux simulator. Wine execution is smoke evidence only, never
native Windows acceptance.

The shell cross-build additionally needs LLVM/LLD, NSIS, Rust's
`x86_64-pc-windows-msvc` target, and `cargo-xwin`, per the official route:
https://v2.tauri.app/distribute/windows-installer/#build-windows-apps-on-linux-and-macos

Do not run the final shell packaging step until a genuine, tested Windows
backend sidecar is available. A shell-only `.exe` does not meet standalone
acceptance.
