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
each VeritX extension is still reachable. It prints which of your files are
**new** and which are **OVERLAY**. Re-run after every edit — it is the "did I
break it" check.

You never touch the `Dockerfile`, Booksim's Makefile, or `veritx_hooks.patch`.

## Two ways in, and when to use which

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

## How the hook works

`veritx_hooks.patch` is the **only** patch and it is permanent — 10 lines giving
Booksim's two factories a fallback into this folder:

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
- **Bumping the pinned Booksim commit** can invalidate `veritx_hooks.patch` (loud
  failure, good) *and* stale your overlays (silent, bad). Re-check both.
