# Troubleshooting — every build/run issue hit + the hassle-free path

## The hassle-free path (read this first)

* ASTRA legs: always go through `veritx evaluate astra` / `veritx topology diff`
  (they pass the injection override, DEVNULL stdin, absolute paths). Raw binary
  invocations must replicate all three — see failures 1, 5, 7.
* Container runs: host-built frontends load via `/opt/hostabi` shims. If you
  rebuild a frontend, re-apply its shim (failures 3, 4).

## 1. Hang: `injected=0`, no `[workload]` lines, process killed by timeout (exit 124)

Cause: `booksim_config.cpp` defaults `injection_rate = 0.1`. Without
`--booksim2-extra=injection_rate=0.0`, `TrafficManager::_Inject()` floods
synthetic uniform traffic alongside embedded ASTRA injection; collective
flits starve forever (observed: 131k flits in flight, zero retirements over
7.6M cycles). Fix: pass the override (the CLI always does). Template cfgs
keep standalone-style traffic lines untouched.

## 2. Spurious `[trace] All N cycles, injected=0 — draining` on embedded runs

The fork's trace-done check was vacuously true with zero
`TraceInjectionProcess`es (EmbedTM injects via API, not processes), and the
counter only counts trace-process packets. Cosmetic only — fixed by gating
on `has_trace` in `trafficmanager.cpp` (both `third_party/booksim2/src`
and `astra-sim/extern/…/src`; keep them in sync). If you see it on a
standalone `sim_type=trace` run, that one is real.

## 3. Rebuild clobbers `bin/AstraSim_BookSim2` (753 B launcher → 4 MB ELF)

`network_frontend/booksim2/CMakeLists.txt` outputs to `bin/`, overwriting the
dual-mode launcher. Fixed with `OUTPUT_NAME AstraSim_BookSim2.real` (ELF goes
to `.real`, launcher survives; verified: rebuild preserves launcher, CLI runs
through it bit-identical). Same hazard applies to any frontend that gains a
shim — check `bin/` after rebuilding.

## 4. `AnalyticalAstra: libprotobuf.so.32: cannot open shared object file` (in-container)

Host-built frontend, image libs too old. Fixed with launcher shims mirroring
BookSim2 (loader + `/opt/hostabi` library path) at:
`astra-sim/…/build/astra_analytical/build/AnalyticalAstra/bin/AnalyticalAstra`
(ELF → `.real`) and the `AnalyticalAstraUnaware` twin. Dep closure verified:
exactly `{ld-linux, libc, libm, libgcc_s, libprotobuf.so.32, libstdc++, libz}`,
all present in-image — no image rebuild needed. Smoke test: no-arg run must
print the app-level options error, never a loader error (host AND `podman exec`).

## 5. All ranks `finished, 0 cycles` — wrong ET path semantics

The frontend resolves `<base>.<rank>.et`. Passing a rank file as base
(`…/all_gather.0.et`) makes every rank miss ("idle NPU, treating as empty")
and exit 0. Always pass the **prefix** (`…/all_gather`). `evaluate astra`
and `topology diff` fail fast when `<base>.0.et` (diff: all ranks) is missing.

## 6. Interactive hang at `Waiting`

After quiescence the binary reads the `load/run/pass/exit/done` protocol from
stdin. Inheriting a terminal hangs forever — pass `stdin=DEVNULL` (EOF exits
cleanly). The CLI does this; see `test_evaluate_astra.py` (would hang then
fail by timeout without it).

## 7. `Unable to open file:` with relative `--system/memory-config`

Binary cwd is REPO, so relative config paths miss. `topology diff` resolves
them via `_resolve_path` (fixed 2026-09-16); `evaluate astra` defaults are
absolute. Rule: resolve user-supplied config paths before subprocess.

## 8. Frontend can't load in-container at all (old libs, no shim yet)

`t3 astrasim` fails fast with the native command instead of `rc=127` rows;
`evaluate astra` is forwardable because the CLI errors clearly when the host
binary is missing. For new frontends: add the `/opt/hostabi` shim first.

## 9. Anynet routing + ring mapping

Arbitrary graphs have no DOR axes — anynet/star/switch/custom legs use
`routing_function = min` (mirrors `_write_anynet_cfg`). BookSim has no ring
topology: TopologyIR lowers ring → 1-D torus (`k=N, n=1`), routing
`dim_order` (torus preset convention).

## 10. `total_nodes` parse errors

BookSim's cfg parser rejects unknown fields (`Parse error: Unknown integer
field`), but the adapter needs explicit counts for closed-form-free
topologies. Rule: emitters include `total_nodes` (TopologyIR does);
`_write_sanitized_cfg` strips it before the frontend parses. Never feed an
unstripped IR cfg to standalone BookSim.
