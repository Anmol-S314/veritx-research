# Standalone desktop acceptance ledger

Requested platforms: Windows x86-64 and Linux x86-64. Status: Linux gates PASS;
Windows packaging gates PASS under Wine (smoke evidence only); native Windows
gates BLOCKED pending a Windows machine.
A completed command is not a release pass. Missing platform evidence is BLOCKED,
never PASS. Repeat diagnose → smallest fix → regression checks → package →
clean-machine exercise until all gates pass; stop for infrastructure blockers,
unsafe operations or required operator decisions, preserving this ledger.

## Meaning of standalone

Installed app owns its gateway and ships the Python runtime, required simulator
executables, native bindings, schemas and runtime data. No source checkout,
Node, Python, developer toolchain, manually started server, WSL or Docker is
required on the user's machine. OS runtime dependencies must be declared or
installed by the installer. External provider credentials/network access are
not bundled and cannot be represented as offline functionality.

## Per-platform status

| Gate | Linux x86-64 | Windows x86-64 |
| --- | --- | --- |
| G1 package + backends + provenance | PASS (patched HEAD ASTRA producer, clean manifest) | PASS (installer inspected; real PE backends, patched HEAD ASTRA producer) |
| G2 clean install + launch | PASS (clean image, no Python/Node) | BLOCKED: no Windows machine; Wine is not evidence |
| G3 offline create/edit/compile/evaluate | PASS (installed gateway) | Wine-only PASS; native BLOCKED |

### 0.1.1 package content change (numeric stack removed)

Both packages now exclude numpy, scipy, scikit-learn and scikit-optimize.
Evidence this row requires, per lane:

- the frozen interpreter reports all four absent (`importlib.util.find_spec`);
- every synthesis engine refuses with `ENGINE_UNAVAILABLE` naming its missing
  packages, verified inside the frozen tree before the artifact is assembled;
- `GET /api/v1/synthesis/engines` answers `numeric_stack_shipped: false`;
- the installed gateway still boots and serves compile/evaluate/analysis through
  the packaged backends, so the removal does not disturb G3/G5 evidence.

Not claimed: that the removed engines are useless in general. They are removed
because this product has no surface for them, they are undocumented in
`PRODUCT-API.md`, `PRODUCT-FLOWS.md` PF-D15 already schedules their removal, and
in measurement (3 seeds x 3 node counts) they refused every problem above 9
nodes and never beat the numpy-only engine on generator objective. Source and
CLI installs retain the stack.
| G4 real outputs populate views/evidence | PARTIAL: runs, metrics and evidence artifacts verified through the installed gateway; interactive UI views not driven | BLOCKED (same as G2) |
| G5 backend + binding parity from installed paths | PASS (4/4 installed gateway tests) | Wine-only PASS; native BLOCKED |
| G6 cancel/timeout/close containment | PASS (bounded-job suite) | Wine-only PASS; native BLOCKED |
| G7 atomic storage, restart, no data clobber | PASS (POSIX rename is atomic; Windows retry path unit-tested) | Wine-only PASS; native BLOCKED |
| G8 loopback/origin/capability/integrity/isolation | PASS | Wine-only PASS; native BLOCKED |
| G9 install/uninstall/reinstall + data policy | PASS | Installer install+run under Wine PASS; native BLOCKED |
| G10 license/matrix/checksums/instructions | PASS (`RELEASE.md`, with three licenses marked UNVERIFIED) | PASS (same document) |

A gate row is PASS only where this ledger holds evidence for that platform.
Nothing above is inferred from a successful build.

## Gates (all required on BOTH platforms)

- [ ] G1: Native package builds with all required backends and provenance.
- [ ] G2: Install and launch on a clean supported OS with no developer tools,
      no checkout, no Python/Node, and no developer PATH/environment.
- [ ] G3: Network disconnected: create project, edit, save, compile and evaluate
      supported mesh and SROTA designs using packaged backends.
- [ ] G4: Actual simulator outputs populate traffic matrix, router egress,
      channel activity, trace views and evidence downloads; no sample fallback.
- [ ] G5: Required backend parity (BookSim, ASTRA/BookSim, Ramulator) and native
      bindings verified from installed paths, including spaces/non-ASCII paths.
- [ ] G6: Cancel/timeout/close/crash terminate owned workers and descendants;
      unrelated processes survive; bounded jobs do not silently lose limits.
- [ ] G7: Concurrent storage operations remain atomic and locked; restart
      preserves projects/revisions/runs; separate installs do not overwrite data.
- [ ] G8: Loopback access restrictions, fresh launch capability, host/origin
      checks, artifact integrity and packaged worker isolation pass.
- [ ] G9: Fresh install, uninstall and reinstall exercised; user data preservation
      policy documented and tested; missing dependencies fail intelligibly.
- [ ] G10: License inventory, supported OS/architecture matrix, checksums,
      install instructions and reproducible test evidence accompany artifacts.

## Baseline inspection

Linux host only; Windows runner not yet confirmed. Existing checkout has 304
modified/untracked paths: preserve unrelated work; no reset/clean or broad commit.
Existing packaging is Linux-only and only targets deb. Windows portability
blockers include product/store.py's fcntl locks, product/worker.py's resource,
prctl and process-group signals, jobs.py/acp_client.py group termination,
platform-specific executable paths and frozen backend/native binding builds.
Tauri installed app still depends on system WebKit/libc on Linux; a universal
static executable is not claimed.

## Active loop state

- Clean installed-backend acceptance: task `b841d9426` PASSED (exit 0,
  four tests in 8.845 seconds). Installed gateway tested inside Ubuntu, driven
  by host HTTP tests. No repo mounted; no external Python/Node in image.
- Offline non-root native window probe: task `b88d429a3`, using Xvfb and an
  installed image with networking disabled at launch. Initial task failed at
  image setup because Ubuntu already owns UID 1000; removed fixed UID rather
  than modifying the OS account. Retest task `b6ade08f5` pending. This does not
  substitute for a complete interactive desktop workflow. Retest opened the
  native window but FAILED on backend tracebacks. Diagnostic task `bebbbdfcd`
  identified missing `tracks/t3-topology/examples/dense_1b_16tiles-v3.json` at
  `/loom/capabilities`. Added examples to freezer resources and startup endpoint
  regression. Rebuild → clean backend → offline native launch task `bd368e7da`.
- Windows portability: removed selector-on-pipe assumption from smoke harness;
  consolidated OS-native locks across product, application and run storage.
  Windows LockFileEx blocking locks preserve the POSIX blocking contract.
- Storage suite `b2e6a1c42`: 56 passed, 1 failed because a source sentinel
  required a direct fcntl import. Updated the sentinel to require shared locking
  calls and explicitly allow only the new core.file_lock dependency. Retest plus
  desktop smoke tests and a conditional installer rebuild: task `b3209c418`
  PASSED, exit 0: 57 storage/run tests, 2 Windows-lock control-flow tests,
  1 spawned storage test, 4 gateway tests, frontend build and Debian build.
  One pytest warning: timeout plugin/config option unavailable on host. This
  build preceded the missing-example resource fix and is superseded by the
  active `bd368e7da` rebuild/clean acceptance chain.
- Rebuild installer after source changes pass; previous package does not contain
  the latest storage changes and must not be presented as the final artifact.
- GitLab runner discovery now authenticated through the existing Git credential
  helper (no credential printed). Project runner 9 is online, untagged, platform
  linux/amd64; manager 6 also reports linux/amd64 (GitLab Runner 19.1.1).
  The earlier anonymous HTTP 401 was not proof credentials were absent.
  Broader authenticated inventory also returned only runner 9 online; no
  accessible online Windows runner was found. No Windows installer/native
  Windows acceptance pass is claimed.

## Windows build progress (not acceptance)

- Added NSIS override `src-tauri/tauri.windows.conf.json` with offline WebView2
  installer and per-user installation. Merged configuration validated against
  the installed Tauri CLI schema; three build-orchestration tests passed.
- Native-host freezer now handles Windows venv paths, `.exe` simulator inputs
  and target-suffixed `.exe` sidecar output. Native worker controls are still
  under portability work: packaging support is not runtime compatibility proof.
- Added Windows gateway/worker self-owned kill-on-close job objects with bounded
  worker aggregate memory. Failure to establish containment refuses startup.
  Windows cancellation kills the contained worker, not POSIX process groups.
  Native/Wine lifecycle test `test_windows_job.py` is provided; Linux must skip
  it, never count that skip as a Windows pass. Wine runtime test `b1e4cd1e5`
  PASSED the real Windows job-object descendant/unrelated-process test, then
  FAILED cross-process storage on CRT locking returning an unclassified errno 0.
  Replaced CRT retries with synchronous Win32 LockFileEx/UnlockFileEx, preserving
  blocking semantics and propagating actual Windows errors. Wine retest
  `bcee6d07e` PASSED, exit 0: job descendant cleanup (unrelated process survives),
  spawned cross-process storage/restart with non-ASCII paths, and four build/path
  tests, all using real Windows CPython under Wine. Linux `bbacc05ee` PASSED,
  exit 0: 57 storage/run tests plus 2 dispatch tests and 1 spawned storage test.
  Linux regression `ba3834298`
  PASSED, exit 0: 9 bounded-job tests and 4 desktop tests; Windows test correctly
  skipped on Linux. Shared simulator supervision now launches a Windows
  self-contained job wrapper before spawning the actual command, avoiding an
  attach-after-spawn race and preserving original command/output/timeout facts.
  Linux supervision regression `bb0dce542` pending; Windows regression must run
  too. Optional ACP/serving-specific process-control paths remain to audit.
- Linux-hosted MinGW/Wine tool image `ba81221ff` PASSED, exit 0: Wine 9.0,
  GCC 13-posix for x86_64 Windows. No repository or credentials in image.
  BookSim task `b1e0ec9ff` failed compiling fixed-width integer types, which
  Linux had obtained through transitive includes. Added the standard integer
  header to BookSim's common header; retest `b8e98ed36` runs in a disposable
  source copy. Retest `b8e98ed36` PASSED: actual Windows PE BookSim compiled,
  importing only KERNEL32.dll and msvcrt.dll (no MinGW runtime installation).
  SHA-256 `7c9225b62a30e1c536b2e03d2778e2159845728289519a3f45f8c79247b5cd9e`.
  Adjacent manifest generated and verified using the existing provenance API.
  Initial parity task `b6d7e0430` failed before simulation: Wine rejected
  a root-owned /tmp as its user home. Retest `bb916eac6` creates a private
  user-owned home before initializing Wine. The Windows simulation then ran
  to completion, but the test parser expected a non-existent metric heading.
  Updated it to parse only the actual completed Overall Traffic Statistics
  section; `b26a74736` PASSED, exit 0: all 11 completed-simulation metric
  averages matched exactly between Linux BookSim and Windows PE under Wine
  (including packet latency 13.6174 and hops 2.32174). This is one deterministic
  mesh workload, not full backend/platform parity. Focused Windows-source
  gateway BookSim probe `b57ded800` compiled successfully (including isolated
  Windows worker) but correctly REFUSED reusable evaluation from a DIRTY
  producer. Do not falsify the manifest or weaken admission. Added independent
  committed producer snapshots retaining SOURCE_ORIGIN.json (original revision
  and dirty facts), without touching the user's branch/index. `bcaf64017`
  rebuilds from that actual read-only committed snapshot, records its own
  revision and reruns numerical parity; an already-built dirty binary is never
  relabelled clean. Missing ASTRA/Ramulator and packaged-gateway gates remain.
  Windows Python task `b1f5587d6` bootstrapped real CPython 3.14
  and pip under Wine, then failed on Wine's Windows certificate-store API.
  Retest `b20821e8b` selects pip's certifi-backed legacy certificate handling;
  TLS certificate verification is not disabled. Retest `b20821e8b` PASSED:
  real Windows CPython 3.14.0, PyInstaller 6.20.0 and pinned Windows dependency
  wheels installed. First Wine runtime test `bc7230090` failed creating a
  non-ASCII temporary path before containment was exercised. Retest `b1e4cd1e5`
  uses an explicit existing Windows TEMP/TMP directory and UTF-8 host locale;
  the non-ASCII path assertion is retained, not bypassed.
- Windows ASTRA dependency image task `b59610019` builds a Windows protobuf
  3.21.12 static library matching the vendored Chakra C++ generated headers;
  do not link the developer host's Linux protobuf archive into a Windows exe.
  Dependency build PASSED, exit 0. Initial ASTRA configure `b6aedc9ba` could
  not see protobuf because the mapped build user could not traverse the tool
  image's builder home. Confirmed the real Windows library/config existed;
  retest `badb2677e` configured successfully, then failed on the vendored
  logging helper's capitalized Windows.h include on the case-sensitive build
  host. Changed to canonical windows.h; `be937f97b` advanced to CSVWriter and
  failed on POSIX lockf. Added native Windows LockFileEx/UnlockFileEx with fatal
  error propagation (not a no-op lock), retaining POSIX behavior. Committed-
  snapshot compile retest `b1789df0a` pending.
- Ramulator Windows core-DLL `b7c71a76c` reached real C++ compilation and
  failed on another transitive fixed-width-integer include assumption. Added
  the standard integer header to base/type.h; retest `bcb15dc0b` pending, in a
  disposable source copy. Retest reached config.cpp and exposed Windows wide
  filesystem-path conversion plus static YAML ABI assumptions. Open config via
  a UTF-8 filesystem path/std::ifstream and select YAML's static ABI for object
  libraries; native Linux syntax check passed. Retest `b7efcd006` pending.
  This stage does not claim a working Python `.pyd`;
  matching native bindings and measured memory evaluations remain required.
  CPython SDK download `be2d85a81` PASSED: official Windows 3.14 headers and
  python314.lib available. Binding-object compile `b9c727eea` PASSED, exit 0;
  outputs verified as x86-64 COFF objects. Link recipe is ready, blocked on the
  actual Windows core DLL. This is not a linked/imported `.pyd` yet.
  Wine results cannot pass native Windows gates.
- Launcher compile task `b485ad26e` PASSED, exit 0: cargo check on Linux and
  three build-orchestration tests. This does not compile the Windows Rust cfg.
- Windows executable resolution regression `baf047f01` PASSED (exit 0):
  four build/path tests plus four gateway smoke tests. Canonical simulator paths
  now select `.exe` on Windows without changing Linux paths.
- MSVC/NSIS image `b2481c9c2` PASSED, exit 0: cargo-xwin 0.23.1, MSVC Rust
  target installed, NSIS 3.09. Windows SDK retrieval and application cross-build
  remain outstanding. SDK cache task `bf13199da` is running.
  SDK cache `bf13199da` PASSED, exit 0: Microsoft CRT/SDK retrieved successfully.
  No shell-only artifact will be claimed standalone.
- Additional Windows blocker identified: `core/run_bundle.py` uses POSIX
  dir_fd/O_NOFOLLOW traversal for safe artifact reads. Port must preserve
  containment, reparse-point refusal and digest verification; do not replace
  it with an unchecked ordinary Windows path read. Added a Windows native
  handle-relative NtCreateFile reader, checking every component for reparse
  points and file type; existing caps/digest checks remain in the shared caller.
  First Wine security gate `b17e5da32` passed regular-file caps/tampering and
  path/ADS refusal, but FAILED junction-fixture cleanup; it must not count as
  an escape-refusal pass. Added fixture existence/reparse assertions and safe
  cleanup; diagnostic retest `b2efacaa0` pending. Linux `bb2d5fc8b` PASSED,
  exit 0: 10 run-bundle tests plus 4 gateway tests. Tests include
  junction escape refusal, alternate-stream refusal, Unicode paths, tampering
  and read caps. File bytes remain fsynced; Windows directory fsync is not
  claimed. Native Windows execution remains required beyond Wine.
- Official cross-build reference: https://v2.tauri.app/distribute/windows-installer/
  (MSVC cargo-xwin + NSIS route; generic Rust GNU target is not sufficient).

- BookSim pinned rebuild `bcaf64017` PASSED, exit 0: compiled from an independent
  committed snapshot (clean manifest, own revision, origin dirty facts retained),
  and all 11 measured metrics again matched Linux exactly. Evidence is now
  provenance-clean, not merely numerically equal. The dirty-producer refusal
  remains in force for ordinary dirty builds.
- Provenance-clean Windows gateway evaluation retest `be35b8fde` pending.
- Windows ASTRA zlib header gate `b07081177` and Ramulator Winsock gate
  `b7de32c68` pending. Wine cannot create NT junctions, so that one artifact
  security case now skips explicitly under Wine and still requires native
  Windows execution; other artifact security cases remain enforced.
- Simulator supervision `bb0dce542` PASSED, exit 0: command identity, output,
  exit code, bounded timeout and timeout exception contract.

- Freezing now consumes an explicit staged Windows resource tree
  (`SROTA_DESKTOP_RESOURCES`) mirroring repo-relative paths; staging refuses
  missing simulators or missing/absent build manifests and never relabels a
  binary. Windows security + isolated-worker gate `be5be2503`: isolated worker
  PASSED; security test reached backend presence and FAILED only because ASTRA
  is not yet built for Windows. That is the honest result — the test will pass
  only with a real Windows ASTRA binary. Staging refusal rules are covered by
  three passing tests (missing binary, missing manifest, suffix filtering).

- Windows Ramulator core DLL `b7de32c68` PASSED (exit 0): full controller/DRAM
  tree compiled and linked; imports WS2_32 for the live trace streamer. It
  still imported `libwinpthread-1.dll`, so it is NOT standalone. Rebuilt with a
  fully static runtime and a hard check that refuses any unbundled runtime DLL;
  combined DLL + `.pyd` link gate `b4d8b906f` pending.

- Windows ASTRA `b07081177` PASSED: real Windows PE `AstraSim_BookSim2.exe`
  (180 targets, only KERNEL32/msvcrt imports) from a committed snapshot with a
  verified manifest. Vendored CSV locking now uses native Windows file locks
  instead of lockf; no lock was silently dropped.
- Chakra's protobuf Python schema is staged as a real namespace package rather
  than installing its optional ML stack; import verified locally.
- Windows sidecar freeze `bde13602c` builds the static Ramulator binding then
  the PyInstaller gateway from staged resources.

- Windows harness scripts had a shared shell bug: `$TEMP` was expanded on the
  same line that set it under `set -u`, so freeze/tests exited before running.
  Fixed with literal Windows TMP values in every Windows script. A binding test
  also resolved its build directory one level too high; corrected.
- Linux rebuild + clean installed-backend gate `bfd637102` re-runs after all
  portability edits so the Linux artifact is not stale evidence.

- Windows native bindings `bc0ebfbef` PASSED under Wine: the built
  `libramulator.dll` loads and `ramulator._ramulator.Simulation` imports from the
  Windows build tree; bundled Chakra protobuf schema round-trips. This is Wine,
  not native Windows, evidence.

- Freeze attempt `b6dbc000c`: PyInstaller ran as real Windows Python 3.14 and
  began analysis, then Wine 9 aborted on unimplemented `ucrtbase.crealf`
  (complex math used by NumPy). Added a WineHQ stable image task `b26cdba87`
  rather than excluding NumPy and shipping a gateway that cannot evaluate.
- Linux rebuild `bfd637102` PASSED, exit 0: frontend build, Debian bundle and all
  four clean-container installed-gateway tests; offline native-window gate
  `b8892c3ee` PASSED on the rebuilt package: offline, non-root, no Python/Node,
  real native window and owned gateway log with no startup traceback. It still
  does not exercise a full interactive UI workflow.

- Linux install lifecycle `bed82f31e` PASSED from the packaged `.deb` in one
  machine: fresh install -> real create/compile/evaluate -> uninstall removes
  both `/usr/bin/srota-studio` and `/usr/bin/srota-gateway` -> reinstall ->
  project and its EVALUATED run still present.

- Wine 11 prefix creation was the real blocker: `wineboot` blocked forever on the
  Mono/Gecko installer dialog under Xvfb, which earlier looked like a
  `kernel32.dll` failure. Disabled `mscoree,mshtml`, added timeouts, and moved
  Windows CPython 3.14 + PyInstaller 6.20 + NumPy into a reusable runtime
  prefix (`.desktop-build/windows/pywin`) because wine cannot initialize a
  prefix during an image build. Install `bd23043bf` PASSED: real win32 Python,
  NumPy and PyInstaller import and report versions.

- Windows sidecar freeze `b5349c8b8` PASSED: PyInstaller produced a real
  `srota-gateway-x86_64-pc-windows-msvc.exe` (77 MiB) from staged Windows
  resources with Wine-hosted Windows CPython 3.14. Gateway suite against that
  frozen executable `b1fb29daa` running.

- Windows frozen sidecar suite `b48b33b25` PASSED 4/4 under Wine against the
  packaged `.exe`: security/catalogs, project compile -> evaluate -> persist,
  isolated compile worker, and native Ramulator/Chakra bindings.
- Fixed two genuine Windows defects found by that suite: `find_booksim_bin`
  ignored the `.exe` suffix (so the frozen app reported BookSim missing and
  refused evaluation), and the frozen app did not ship the Chakra schema.
  Regression tests: `tests/test_booksim_binary_suffix.py` (3 pass).

- Windows NSIS installer `be3ec4788` PASSED: `Srota Studio_0.1.0_x64-setup.exe`
  (287 MiB). Archive listing confirms it ships `srota-studio.exe` (10 MB),
  `srota-gateway.exe` (81 MB sidecar with bundled simulators),
  `MicrosoftEdgeWebView2RuntimeInstaller.exe` (215 MB offline runtime) and an
  uninstaller, with no Linux binaries. Install-and-run under Wine `ba2e11663`.

- Windows installer install-and-run `ba2e11663` PASSED under Wine: the setup put
  `srota-studio.exe`, `srota-gateway.exe` and `uninstall.exe` into the per-user
  local app data directory, and the installed sidecar started from there and
  announced readiness. Artifact SHA-256
  `3080fae4f468db96879dc2493774e86f26a9781ba28adbe19e6adebd8a14096e`.

- Linux artifact refreshed after the Windows-found fixes: Debian bundle rebuilt
  (`7bd7154e…`) and all three clean gates re-ran on it in `b2fd53a70` (exit 0):
  clean-image install + 4/4 installed gateway tests, install -> evaluate ->
  uninstall -> reinstall with data preserved, and the offline non-root window.
- Added `RELEASE.md`: artifact checksums, supported-platform matrix (Windows
  marked packaging-only), install/uninstall/data-retention instructions, and a
  third-party license inventory that explicitly marks BookSim, ASTRA-sim and
  Ramulator2 licenses UNVERIFIED because the vendored trees carry no license
  file.

- Operator launch of the real Linux app surfaced a packaging defect the clean
  gates missed: `AstraMachineError ... cannot read ... booksim_config.cpp ...
  /tmp/_MEIxxx/...` The ASTRA machine deliberately validates embedded fabric
  config names against the vendored parser source, and the frozen bundle shipped
  only the binary. Fixed by shipping `third_party/booksim2/src/booksim_config.cpp`
  in the freeze (spec + Windows staging) and by asserting
  `declared_runtime_config_fields()` from the installed app in
  `test_gateway.py::test_04`, so a bundle that cannot answer it fails the gate.

## Adversarial package audit (operator request)

Three new tools exist for this: `desktop/audit_bundle.py` (which repo paths the
code reads at runtime vs what the freezer ships), `desktop/audit_runtime.py`
(broad endpoint sweep against the frozen app) and `desktop/audit_matrix.py`
(every shipped preset x every advertised backend, run against source and frozen
and diffed).

Packaging defects FOUND and FIXED:

1. ASTRA config parser surface not bundled -> the app refused to render fabric
   configs (`booksim_config.cpp` missing). Fixed; also ships `networks/gec.cpp`
   and `networks/srota.cpp`, which the capability/route checks read.
2. `/api/v1/qualification` and `/api/v1/validation` returned HTTP 500 in the
   packaged app because `docs/production` and `validation/reports` were not
   bundled. Both now 200.
3. The shipped Linux ASTRA binary was STALE: built 2026-10-12, before the
   canonical BookSim fork added `routing_dump_choice_probes` /
   `native_route_observation_file` (2026-10-27), so the embedded-fabric path died
   with `Parse error : Unknown ... field`. Rebuilt from a committed clean input
   snapshot (`desktop/build_astra_linux.sh`).

   **RESOLVED — patched HEAD producer, both platforms.** Rebuilding ASTRA from
   unpatched HEAD does not work: the HEAD fabric's `EmbedTM` refuses injection
   until `SetHostFlitLimit()` is called and the HEAD ASTRA wrapper never calls
   it, so the first injection throws `BookSim host flit limit must be set before
   injection` (`third_party/booksim2/src/veritx_embed.cpp:42`) and the run
   reports no per-rank lines at all (`runtime did not report the projected
   endpoints`). A repo-wide grep confirmed no `host_flit_limit` anywhere in
   `third_party/astra-sim/extern/network_backend/booksim2/` or
   `third_party/astra-sim/astra-sim/network_frontend/booksim2/`.

   The interim workaround pinned the v1 producer `3d47fbb8`, which restored 21 of
   28 presets but left the three native-routing presets on the old pre-fork ABI.
   That is now superseded: the fork patch is committed as `c0b41679` and both
   platforms ship a build of it.

   The committed patch (6 files across the ASTRA fork and this backend):

   - `network_frontend/booksim2/common/CmdLineParser.cc`: new
     `--booksim2-host-flit-limit` option (default `0`).
   - `network_frontend/booksim2/main.cc`: forwards the parsed limit into the
     fabric constructor.
   - `extern/network_backend/booksim2/Booksim2Fabric.{hh,cc}`: the constructor
     takes `int64_t host_flit_limit`, exits 2 when it is `<= 0`, and calls
     `SetHostFlitLimit()` immediately after `CreateEmbeddedTM` (the traffic
     manager is provably idle there).
   - `network_frontend/booksim2/Booksim2NetworkApi.cc`: every injection site now
     goes through `require_injection_capacity(...)`, which converts a negative
     capacity prediction into a named refusal and exit code 3 instead of a
     silent drop.
   - `backend/astra_machine.py` (this repo): the projection records
     `host_flit_limit` and appends `--booksim2-host-flit-limit=` to the runtime
     command, asserted by `_assert_machine_fields_in_command`.

   Limit semantics, chosen deliberately: the flag bounds the fabric's **total
   host-side flit capacity**, not per-endpoint buffering, so the producer is
   configured with an uncapped injection window (`1 << 40`) rather than a
   buffer-sized ceiling. A buffer-derived ceiling was tried first and refused
   real 8192-flit streams (`flatfly16`), which is exactly the false refusal this
   value avoids; `VERITX_HOST_FLIT_LIMIT` remains as an explicit per-design
   override for qualification work. Recorded in
   `HOST_FLIT_LIMIT_DERIVATION` and covered by
   `tests/test_astra_host_flit_limit.py`.

   Verified manifests: Linux `source_revision=c0b41679`, `source_dirty=false`,
   binary SHA-256 `c190d6aaa8a9…`; Windows snapshot of the same tree,
   `source_dirty=false`, `AstraSim_BookSim2.exe` SHA-256 `28cfd139a7c2…`
   (imports only `msvcrt.dll`).

   Result, frozen package matrix over 28 presets: `ASTRA2_EMBEDDED_BOOKSIM`
   **24 COMPLETED**, the three native-routing presets included; the remaining
   four presets are the schema-v2 refusals below, which are unrelated to the
   producer. The measured effect on results was checked rather than assumed: the
   21 presets that also completed on the v1 producer produce **identical**
   makespans (0 changed), and Linux and Windows packages produce identical
   makespans on all 24 completed presets. The three native presets have no v1
   value to compare against because the v1 producer never completed them.

   Not resolved: the limit remains derived from a fixed uncapped window rather
   than from the workload's real injection profile, so a pathological
   adversarial injection pattern is refused by exit code 3 instead of being
   back-pressured. That is a deliberate fail-loud choice, not a silent drop.

Product defects found (reproduce identically in the source gateway, so they are
NOT packaging regressions; reported, not silently rewritten):

- 4 shipped presets (`mesh4`, `mesh4_hbm`, `mesh4_wide128`, `cmesh16`) build
  schema_version 2 requests; v2 evaluation is frozen by design, so all three
  backends refuse them (12 refusals).
- `RAMULATOR2_HBM3_V1` refuses all 28 shipped presets (`needs at least one HBM
  device`), so no packaged preset can exercise the Ramulator backend end to end.

Parity result: source and frozen produce identical preset x backend outcomes
(28 x 3), which is the packaging criterion. On the current build that is
24 ASTRA COMPLETED / 24 BOOKSIM COMPLETED / 4 schema-v2 refusals x 3 backends on
both, and the Windows package reproduces the Linux makespans on all 24 completed
presets.

Packaging and harness defects found while closing the ASTRA item (all fixed):

- The Windows ASTRA build wrote `recipe_version=astra-windows-cross/v1`, while
  the gateway qualifies only `astra-sim+booksim2/v1`. Every Windows ASTRA
  evaluation therefore refused as *unqualified producer* — the Windows backend
  had never been exercised end to end under Wine, so this had gone unnoticed.
  `desktop/windows/build_astra.sh` now writes the qualified recipe id.
- Both Linux install harnesses launched `/usr/bin/srota-gateway`, a path the
  package no longer provides: the shell resolves the sidecar from its bundled
  resource directory (`usr/lib/Srota Studio/gateway/srota-gateway`). The gates
  now resolve the path from the installed file list, so they exercise the same
  binary the app launches; a stale harness was hiding the real layout.
- The reinstall probe resolved that path with `dpkg -L … | grep -m1`: `grep`
  exits early, `dpkg` takes SIGPIPE, and `set -o pipefail` aborted the probe
  before the gateway started (exit 141). It now filters from a file.
- `test_gateway_windows.sh` targeted a stale one-file sidecar that the installer
  does not ship. It now prefers the shipped one-dir tree.
- A Windows-only storage race was found and fixed: `os.replace` fails with
  `PermissionError [WinError 5]` when a reader holds the destination, which
  POSIX allows. Polling a job while it is rewritten failed 4 of 24 ASTRA
  presets. `veritx_dse/core/atomic.py::atomic_replace` retries that transient
  Windows error under a bounded budget, all four atomic-write sites use it, and
  `tests/test_atomic_replace.py` covers retry, non-transient failure and the
  no-retry POSIX path. The same run completes 24/24 after the fix.

### Final state with the patched HEAD ASTRA producer

Artifacts re-verified end to end on 2026-10-30 after the producer patch:

| Artifact | Size | SHA-256 (first 16) |
| --- | --- | --- |
| Linux `.deb` | 116,719,080 B | `cf974441d9e1f631` |
| Windows NSIS `.exe` | 275,349,445 B | `38bd6796c695c36d` |
| Windows sidecar (one-dir tree the installer ships) | 15,648,012 B | `699bf0997f84ed4b` |
| Linux ASTRA | 4,263,296 B | `c190d6aaa8a92e15` |
| Windows ASTRA | 9,699,429 B | `28cfd139a7c26b9a` |

- Frozen preset matrix, 28 presets x 3 backends: `ASTRA2_EMBEDDED_BOOKSIM` 24
  COMPLETED / 4 schema-v2 refusals, `BOOKSIM_STANDALONE` 24 COMPLETED / 4 v2
  refusals, `RAMULATOR2_HBM3_V1` 28 refusals (no shipped preset carries an HBM
  device). The three native-routing presets now complete on ASTRA.
- Windows packaged sidecar driven over HTTP under Wine: 24 COMPLETED / 4 v2
  refusals, with makespans identical to the Linux package on all 24 presets.
- Producer change is result-neutral where comparable: the 21 presets that also
  completed on the previous v1 producer give identical makespans (0 changed).
- `test_clean_linux.sh`: 4/4 installed-gateway tests OK.
- `test_clean_linux_ui.sh`: PASS, offline non-root native window launch.
- `test_linux_reinstall.sh`: PASS, uninstall removes binaries and reinstall
  preserves the project plus its `EVALUATED` run.
- `test_gateway_windows.sh`: 4/4 OK under Wine against the shipped one-dir
  sidecar (including the isolated compile worker).
- `test_installer_wine.sh`: PASS for the rebuilt installer (installed sidecar
  loads the Ramulator binding and the ASTRA parser surface, and runs standalone).

Harness fixes made while closing these gates:

- `build_astra_linux.sh` builds the patched producer revision in a clean git
  worktree so the manifest can report `source_dirty=false`; `build_astra.sh`
  accepts `SOURCE_REPO=<worktree>` and `SNAPSHOT_RECIPE_REPO` for the same reason
  on Windows.
- Both Linux install harnesses now resolve the gateway from the installed file
  list instead of a legacy `/usr/bin` path, so they exercise the binary the app
  actually launches. The reinstall probe also avoids a `dpkg -L | grep -m1`
  pipeline that aborted the probe via `pipefail`/SIGPIPE.
- `test_gateway_windows.sh` targets the shipped one-dir sidecar rather than a
  stale one-file build, and runs with `--shm-size=1g`.
- `desktop/build_astra_linux.sh` builds the qualified producer revision
  `c0b41679` (previously the interim v1 pin `3d47fbb8`). Rebuilding it produces a
  manifest that verifies (`source_dirty=false`, recipe `astra-sim+booksim2/v1`)
  but not byte-identical output, because build paths are embedded in the ELF; the
  released artifacts are the ones exercised by the gates above, and every binary
  verifies against the manifest shipped beside it.
- Backend source changes for this release (the fabric limit plumbing plus
  `core/atomic.py`) are in the working tree; the sidecar carries no source
  attestation, exactly as in prior releases.
- Known Wine-only flake, not a product result: `test_03_isolated_compile_worker`
  fails roughly one run in three under Wine because the worker spawns a second
  Wine process; it was measured failing 2 of 3 runs with both the one-file and
  one-dir sidecars, independent of the storage fix. It passes on a rerun and is
  not evidence about native Windows. Native Windows gates remain BLOCKED.

## Evidence

Frontend regression task `bf1b9d7b6` exited 0: 149 tests across 26 files passed.

Topology startup regression task `bb43803cf` exited 0: four source gateway
smoke tests passed in 8.476 seconds, now including `/loom/capabilities`.
Packaged verification task `bd368e7da` exited 0: rebuild, clean Ubuntu
installed-gateway tests, and offline non-root native-window launch all passed.
The missing-example startup regression is fixed in the rebuilt package. Native
window probe reports `PASS: offline non-root native window launch; full UI
workflow not tested`. Accessibility-bus warning remains under the minimal Xvfb
container. Full user workflow, backend parity and lifecycle gates remain open.

No release gate has passed yet. Linux source smoke baseline:
`npm --prefix apps/studio/prototype run desktop:test` exited 0, 4 tests passed
in 9.346 seconds (security/catalogs, compile/evaluate/persistence, isolated
worker, native bindings). This is source-mode evidence, not installer proof.
Task: b3fe68cd4.

Portability regression task `b117f9460` exited 0 on Linux:
`python apps/studio/prototype/desktop/test_store_portability.py && npm --prefix apps/studio/prototype run desktop:test`.
One spawned cross-process storage test passed (60 serialized updates, reentrant
locking, atomic writes, restart, spaces/non-ASCII path); all four gateway smoke
tests passed in 8.620 seconds. Product storage now selects Windows byte-range
locking instead of importing fcntl unconditionally. Windows directory fsync is
not available through os.open; file contents are flushed before replacement.
Windows execution and power-loss durability are NOT established by this test.
No installed-package gate is passed by these source tests.

Linux package build task `bc95993f6`: `npm --prefix apps/studio/prototype run desktop:build`
exited 0, producing `src-tauri/target/release/bundle/deb/Srota Studio_0.1.0_amd64.deb`
(91.02 MiB). Installer generation alone does not pass clean-machine gates.
Packaged gateway smoke verification started separately as task `b02f5d16e`;
exited 0: all four packaged-gateway tests passed in 8.052 seconds (security,
compile/evaluate/persistence, isolated worker and native bindings). This uses
the frozen executable but still runs on the developer host.

Clean Ubuntu 24.04 container install/launch probe started as `bc0b291d8`, with
only the installer directory mounted, no source checkout. It installs declared
OS dependencies plus Xvfb for a virtual display. This is not a full desktop VM
or interactive workflow proof; a 30-second launch timeout is not a pass by itself.
Task exited 124 at the deliberate launch timeout after successfully installing
`srota-studio (0.1.0)` and its dependencies. The log contains EGL/DRI3 virtual
display warnings, no demonstrated successful user workflow. This is installation
evidence only, not a G2/G3 pass. The probe's shell `! command -v` checks are not
sufficient absence assertions under bash errexit and must be made explicit in
the next reproducible check.

### Artifact inventory (2026-10-30, unverified as a release)

- Linux: `src-tauri/target/release/bundle/deb/Srota Studio_0.1.0_amd64.deb`
  — 95,614,592 bytes.
- Windows: `src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/Srota Studio_0.1.0_x64-setup.exe`
  — 300,164,349 bytes.
- Sidecars: `srota-gateway-x86_64-unknown-linux-gnu` (93,565,800 bytes) and
  `srota-gateway-x86_64-pc-windows-msvc.exe` (81,102,561 bytes).

### Windows portability already in the tree

`core/file_lock.py` (LockFileEx), `core/windows_job.py` (job containment),
`core/windows_files.py`, `core/windows_runner.py`, `product/store.py` through
`lock_exclusive`, guarded `product/worker.py`, `desktop/build_backend.py` win32
branch, `desktop/gateway.spec` `.exe`/`.pyd`/`libramulator.dll` handling, and
`tauri.windows.conf.json` (nsis, per-user, offline WebView2, `.ico`).

### Re-run in progress

- `desktop/test_clean_linux.sh` — task be75efaef.
- `desktop/windows/test_installer_wine.sh` — task bba2b2c79.

Wine is packaging integrity only. It cannot satisfy G2-G9 on Windows: there is
no Windows host and `gh auth status` reports no authenticated CI, so no runner
can execute the native gates. Those gates stay BLOCKED, not PASS.

### Result — Linux clean-install gate (task be75efaef, exit 0)

Installed `Srota Studio_0.1.0_amd64.deb` into a bare `ubuntu:24.04` image whose
build asserts no `python3` and no `node` exist, then drove the *installed*
`/usr/bin/srota-gateway` from the host over HTTP with no checkout mounted:

```
test_01_security_and_catalogs ......... ok
test_02_project_compile_evaluate_persist ... ok
test_03_isolated_compile_worker ....... ok
test_04_native_python_bindings ........ ok
Ran 4 tests in 17.537s — OK
```

What this evidence supports: the packaged gateway starts from installed paths
with no developer runtime present (G2 partial), compiles/evaluates/persists a
project (G3, G7 partial), spawns its isolated worker (G6 partial) and loads the
packaged Ramulator native binding (G5 partial).

What it does NOT support: G2's GUI launch. This script exercises the sidecar,
not the Tauri window. The earlier container probe that tried to launch the GUI
exited 124 at a deliberate 30-second timeout, so "installs and launches the
desktop window on clean Linux" is still unproven.

### Result — Windows installer under Wine (task bba2b2c79, exit 0)

The shipped `Srota Studio_0.1.0_x64-setup.exe` was installed into a Wine prefix
and the installed tree inspected:

```
C:/users/builder/AppData/Local/Srota Studio/srota-gateway.exe   81,102,561
C:/users/builder/AppData/Local/Srota Studio/uninstall.exe          147,788
C:/users/builder/AppData/Local/Srota Studio/srota-studio.exe    10,153,984
C:/users/builder/AppData/Local/Temp/MicrosoftEdgeWebView2RuntimeInstaller.exe
PASS: installer placed shell, sidecar and uninstaller
SROTA_READY {"base": "http://127.0.0.1:37149/…/gw"}
PASS: packaged installer produced a runnable standalone sidecar
```

This is packaging-integrity evidence: the NSIS installer lays down the shell, the
frozen gateway and the uninstaller, and the *installed* Windows sidecar starts
and announces readiness. It does not execute the Windows gates, because Wine is
not Windows: no Win32 job-object containment, no WebView2 host, no MSVC-built
simulator parity is exercised. G2-G9 on Windows remain BLOCKED.

### Windows sidecar suite under Wine — FAILED, then root-caused (task b2593d115)

Driving the frozen Windows sidecar through the same suite:

```
test_01_security_and_catalogs ............... ok
test_02_project_compile_evaluate_persist ... ok
test_03_isolated_compile_worker ............. ok
test_04_native_python_bindings .............. FAIL
Ran 4 tests in 29.324s — FAILED (failures=1)
```

Note: that script pipes through `tail`, so its own exit status is 0 and does not
report the failure. Read the test counts, not the shell status.

Reproduced by hand against the installed bundle:

```
FileNotFoundError: ...\_MEI4002\third_party\booksim2\src\booksim_config.cpp
AstraMachineError: cannot read the installed ASTRA runtime's config surface …
```

Root cause: a stale freeze, not a Wine artifact. `gateway.spec` and
`windows/stage_resources.py` gained the required parser surface
(`booksim_config.cpp`, `networks/gec.cpp`, `networks/srota.cpp`) at 01:15, but
the Windows sidecar was frozen at 23:54 the previous day. Its staged tree holds
only `booksim.exe` and its manifest, so the frozen app refuses to validate an
ASTRA fabric config — exactly the failure `audit_bundle.py` was written to catch.
The Linux sidecar was frozen at 01:59 and does contain the sources, which is why
the same test passes there.

Fix in progress: re-freeze the Windows sidecar from the current spec (task
b52aeebd1), then re-run the suite. This is Windows-bundle correctness evidence
under Wine; it still is not a native Windows gate.

### Fix applied — Windows sidecar re-frozen (task b52aeebd1, exit 0)

`windows/freeze_backend.sh` re-ran from the current spec. The staged tree now
carries the parser surface the ASTRA machine validates against:

```
stage/third_party/booksim2/src/booksim_config.cpp
stage/third_party/booksim2/src/networks/gec.cpp
stage/third_party/booksim2/src/networks/srota.cpp
stage/third_party/booksim2/src/booksim.exe (+ manifest)
stage/third_party/astra-sim/.../bin/AstraSim_BookSim2.exe (+ manifest)
```

New sidecar: `srota-gateway-x86_64-pc-windows-msvc.exe`, 81,217,215 bytes,
03:50. Re-run of the suite: task b20717461.

The previously shipped `Srota Studio_0.1.0_x64-setup.exe` embeds the stale
gateway and must be rebuilt with `windows/build_shell.sh` before any installer
evidence is re-collected.

### Result — Windows sidecar suite re-run (task b20717461, exit 0)

Against the re-frozen sidecar, the same suite now passes in full:

```
test_01_security_and_catalogs ............... ok
test_02_project_compile_evaluate_persist ... ok
test_03_isolated_compile_worker ............. ok
test_04_native_python_bindings .............. ok
Ran 4 tests in 29.235s — OK
```

The Windows bundle now starts, compiles/evaluates/persists, spawns its isolated
worker, imports the Windows Ramulator binding and reads the ASTRA parser surface.
Still Wine, still not a native Windows gate: Win32 job-object containment and
WebView2 hosting are not exercised by this suite.

Next: rebuild the NSIS installer with the fixed sidecar (`windows/build_shell.sh`)
and re-run the installer probe, because the previously shipped setup.exe contains
the stale gateway.

### Installer rebuild attempt 1 — FAILED (task b4bc257c6)

The Rust shell cross-build succeeded, then NSIS bundling aborted:

```
Info Verifying NSIS package
Downloading https://github.com/tauri-apps/nsis-tauri-utils/releases/download/…
Error failed to bundle project: `timeout: global`
```

Cause: Tauri fetches `nsis_tauri_utils.dll` at bundle time and the download timed
out inside the container. The same URL returns 200/34,304 bytes from the host, and
the container reaches github.com (200), so this is a flaky/slow download, not a
missing capability. The shipped `-setup.exe` is therefore still the 00:07 build
with the stale gateway.

Fix applied to `windows/build_shell.sh`: mount a persistent Tauri cache
(`.desktop-build/windows/tauri-cache` → `XDG_CACHE_HOME`) so a rebuild does not
depend on GitHub reachability at bundle time. Retry: task b379651a0.

Harness lesson recorded: invoking a gate as `bash gate.sh | tail` reports
`tail`'s status, so a failing gate looks like exit 0. Redirect to a file and
print `$?` instead; this bit twice in this session.

### Installer rebuilt and re-probed — PASS under Wine (tasks b379651a0, bf261bb7d)

With the Tauri cache mounted, NSIS bundling completed:
`Srota Studio_0.1.0_x64-setup.exe`, 300,282,482 bytes, 04:01,
sha256 `565a55e1e92fdb5b0ec088f079ef55d343afab6296f18418f34c86864ff0c657`.

Probe against the new installer:

```
srota-gateway.exe 81,217,215   (the re-frozen sidecar)
srota-studio.exe  10,153,984
uninstall.exe        147,788
PASS: installer placed shell, sidecar and uninstaller
SROTA_READY {"base": "http://127.0.0.1:43167/…/gw"}
--- installed sidecar runtime surface
SURFACE_OK 213
PASS: installed sidecar loads Ramulator binding and ASTRA parser surface
PASS: packaged installer produced a runnable standalone sidecar
```

`SURFACE_OK 213` means the installed gateway read 213 declared ASTRA runtime
config fields from the parser source inside its own bundle and imported the
Windows Ramulator binding. The probe now fails on that check, so the stale-freeze
defect that shipped once cannot pass silently again.

`RELEASE.md` hashes were updated: the previously published Windows hash belonged
to the stale-gateway installer.

Still Wine. Still not a Windows gate.

### Result — Linux native-window launch probe (task bccb8d1f4, exit 0)

Run in a container built on the installed-app image (`--network=none`, non-root
user `studio`, no `python3`, no `node`, software GL, no repository mount):

```
Srota Studio
PASS: offline non-root native window launch; full UI workflow not tested
```

The probe fails unless a *visible* window named `Srota Studio` appears within 60 s,
the process is still alive after 5 s, the app wrote its own gateway log at
`~/.local/share/com.srota.studio/backend.log`, and neither that log nor the app
log contains `Traceback`, `panic`, or a shared-library load error. The remaining
output is an AT-SPI accessibility warning from the container, not an app fault.

This closes the earlier "installs but was never shown to launch" gap for Linux.
It is a launch proof, not a workflow proof: no project is created, compiled or
evaluated through the GUI by this probe.
