# booksim-ext — changing Booksim itself

`src/` here **mirrors Booksim's own `src/` tree** and is copied over it at image
build time. So a file's *path* decides what it does:

| You put | Booksim gets | Because |
|---|---|---|
| `src/myroute.cpp` (new name) | a **new file**, compiled in | Booksim's Makefile globs `*.cpp */*.cpp` — no Makefile edit needed |
| `src/routers/iq_router.cpp` (existing name) | that file **replaced wholesale** | the copy lands on top of upstream's |

That second row is the answer to "can I change the source, not just add config":
**yes — copy the upstream file into the matching path here, edit it, done.** No
patch. It works for anything: `routers/` (router microarchitecture), `networks/`
(topologies), `allocators/`, `arbiters/`, `power/`.

The mirror matters. A *flat* copy would drop `iq_router.cpp` at `src/` **beside**
`src/routers/iq_router.cpp`, both would compile, and the link would die on
duplicate symbols. Keep the path.

**T2 and T3 both run this binary.** A break here breaks both tracks.

## Workflow

```bash
make shell                                    # from the repo root
./tracks/t3-topology/booksim-ext/build.sh     # sync → rebuild → install → verify
```

`build.sh` rebuilds incrementally (a one-file change is seconds), installs to
`/usr/local/bin/booksim`, then checks upstream Booksim still behaves *and* that
each VeritX extension is still reachable (including flit-fork multicast). It prints
which of your files are **new** and which are **OVERLAY**. Re-run after every edit —
it is the "did I break it" check.

For a traffic pattern or routing function you never touch the `Dockerfile` or a
patch. A cross-cutting change to Booksim's internals is the exception — see way 3.

## Three ways in, and when to use which

### 1. Adding a traffic pattern / routing function → no patch, no overlay

These are the common case, and they have a registration hook so you don't have to
overlay Booksim's factory files (which every contributor would then collide on).

1. Write `src/mything.{cpp,hpp}`.
2. Register it with one line in **`src/veritx_ext.cpp`** — the only file you edit.
3. `./build.sh`.

Worked examples, both ~40 lines, neither needing a patch:

| Files | Adds | Used by |
|---|---|---|
| `src/matrixtraffic.{hpp,cpp}` | `traffic = matrix(<file>)` — drives Booksim from a Timeloop traffic matrix | T3 (the Timeloop→Booksim bridge) |
| `src/yxroute.{hpp,cpp}` | `routing_function = yx` — YX dimension-order routing | T2 (mix with XY to close the turn cycle → deadlock) |
| `src/snakeroute.{hpp,cpp}` | `routing_function = snake` — Hamiltonian "boustrophedon" route; a multicast head visits every node so the eject-fork broadcasts to all | T3 (`scripts/prefix_broadcast_flitfork.py` — shared-prefix broadcast) |

### 2. Changing existing Booksim behaviour → overlay the file

Anything the hook can't express — router pipeline, buffer management, allocator,
a new topology class. Copy the file out of the image and into the matching path:

```bash
# inside `make shell`
cp /opt/booksim2/src/routers/iq_router.cpp \
   /workspace/tracks/t3-topology/booksim-ext/src/routers/
# edit it, then:
./tracks/t3-topology/booksim-ext/build.sh
```

**The cost of an overlay:** it pins that file at the version you copied. Bump the
Booksim commit in the `Dockerfile` and your stale copy will *silently* shadow
upstream's new one — no conflict, no error. `build.sh` prints every overlay on
every run so this stays visible. Prefer a new file + the hook when you can; reach
for an overlay only when you genuinely must change existing code.

### 3. A cross-cutting change across several files → a real patch

Some changes touch *several* upstream files at once and can't be a hook (no factory
to register with) or a clean overlay (overlaying whole files like `trafficmanager.cpp`
pins the most-churned files in Booksim). **`multicast.patch`** is the one such case:
the KV schedule's three fabric primitives. **Row-multicast** (`scripts/mcast_flitfork.py`)
needs a dest field + copy list on the `Flit`, an eject-copy fork in `iq_router`, and
multicast injection in the `TrafficManager`; **column-reduce** (`scripts/schedule_fabric.py`)
adds a `reduce_col` relay path in the same injection (the online-softmax combine is in-core,
so the network only forwards partials — no router change); **prefix-broadcast** (`bcast_all`,
`scripts/prefix_broadcast_flitfork.py`) reuses that same eject-fork with the `snake` route to
broadcast one source → all nodes (`bcast_all=1`), against a naive N−1 unicast baseline
(`bcast_all=2`) — a `TrafficManager` injection branch only, no further router change. Six files,
small hunks each.

- It edits only `flit.*`, `booksim_config.cpp`, `trafficmanager.*`, `iq_router.cpp` —
  **disjoint** from `veritx_hooks.patch` (which touches `routefunc`/`traffic`), so the
  two never conflict, and it applies cleanly on the pinned commit.
- Applied at image build (`Dockerfile`, after `veritx_hooks.patch`) and by `build.sh`
  **idempotently** (a rebuilt image already has it baked in; an older image does not).
- `build.sh` verifies it forks: `mcast_k=8` must give accepted/injected ≈ 7 (a booksim
  without the patch delivers 1:1 and fails the check — the point of it).

Regenerate it (from a checkout of the pinned commit with your edits applied):

```bash
git diff HEAD -- src/flit.hpp src/flit.cpp src/booksim_config.cpp \
    src/trafficmanager.hpp src/trafficmanager.cpp src/routers/iq_router.cpp \
    > tracks/t3-topology/booksim-ext/multicast.patch
```

Add a real patch only when the change genuinely spans files this way. One more like it
is fine; a dozen ad-hoc patches is the mess `veritx_hooks.patch`'s hook design avoided.

## How the hook works

`veritx_hooks.patch` is the **factory-hook** patch and it is permanent — 10 lines
giving Booksim's two factories a fallback into this folder (`multicast.patch`, way 3,
is the only other patch, and it is disjoint):

- `traffic.cpp` — when `TrafficPattern::New()` doesn't recognise a pattern name,
  it calls `VeritXNewTraffic()` before erroring out.
- `routefunc.cpp` — `InitializeRoutingMap()` calls `VeritXRegisterRouting()`
  after installing its own entries.

Both land in `src/veritx_ext.cpp`.

The old design gave each feature its own patch against `traffic.cpp`. Two
contributors doing that at once = a guaranteed `git apply` conflict on the same
file, for two changes with nothing to do with each other. The hook exists so that
never happens. `build.sh` refuses to let you overlay `traffic.cpp` or
`routefunc.cpp` for the same reason.

## Gotchas

- **Booksim exits `255` on success.** Its exit code is meaningless — never gate CI
  or a script on it. Read success from stdout (a finite `Packet latency average`),
  which is what `build.sh` and `run_experiments.py` both do.
- **Booksim appends the topology name to `routing_function`.** Map key `yx_mesh`
  is selected with `routing_function = yx;` on a mesh. Passing
  `routing_function = yx_mesh` looks up `yx_mesh_mesh` and aborts with
  `Invalid routing function`.
- **Rebuild ≠ installed.** `make` in `/opt/booksim2/src` leaves the old binary on
  `PATH`; `build.sh` copies it across for you. Don't reach for `BOOKSIM_BIN`
  instead — `make setup` and the sanity tests resolve `booksim` on `PATH`
  (`tracks/common.mk`), so the env var covers only `run_experiments.py` and leaves
  everything else silently on the stale binary.
- **`/opt` is not persistent.** `make shell` runs `--rm`, so edits to
  `/opt/booksim2/src` die with the container. Edit *here*, in the repo (mounted at
  `/workspace`), and let `build.sh` push them across.
- **Bumping the pinned Booksim commit** can invalidate `veritx_hooks.patch` or
  `multicast.patch` (loud `git apply` failure, good) *and* stale your overlays
  (silent, bad). Re-check all three; regenerate `multicast.patch` from the new commit
  if its context shifted (command above).
