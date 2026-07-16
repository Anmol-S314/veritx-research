# Working on BookSim (vendored)

This is **BookSim 2.0, vendored into the repo as a git subtree** — pinned upstream
(`booksim/booksim2` @ `28f43299`) with VeritX's edits carried as ordinary commits on top.

The point: **you edit the real `.cpp` files.** Full LSP, normal git, no patch to
hand-write, no overlay copy, no path mirror. `git diff` shows exactly our delta from
upstream, and a version bump is a normal merge.

---

## Edit → rebuild loop

```bash
make shell                                   # from the repo root
# edit any file under third_party/booksim2/src/ like normal code
third_party/booksim2/veritx-rebuild.sh       # sync → compile → install → verify
```

`veritx-rebuild.sh` compiles incrementally (a one-file change is seconds), installs
`/usr/local/bin/booksim`, and **verifies the multicast still forks** — a build that
silently dropped our edits fails the check. T3's scripts also call it automatically if
they find a booksim on `PATH` that lacks our extensions.

## See exactly what we changed

```bash
git log  --oneline -- third_party/booksim2      # the squashed import, then our edits
git diff <import-commit> -- third_party/booksim2 # our full delta vs pristine upstream
```

Our delta is small and legible — that's the payoff of a subtree over a full-file overlay.

## Bumping BookSim to a new upstream version

A version bump is a **normal git merge**, not a patch-reject or a silent shadow:

```bash
git subtree pull --prefix third_party/booksim2 \
    https://github.com/booksim/booksim2.git <new-commit> --squash
```

- Upstream changed a file we didn't touch → auto-merged, clean.
- Upstream changed lines near ours → a normal merge conflict in a real `.cpp`, resolved
  in your editor with full context.
- Commit the merge; update the pinned commit noted at the top of this file. Then
  `veritx-rebuild.sh` and rerun the T3 gates.

---

## What VeritX added (the delta)

New files (BookSim's Makefile globs `*.cpp */*.cpp`, so new files just compile in):

| File | Adds |
|---|---|
| `src/veritx_ext.{cpp,hpp}` | factory hook — register routing fns / traffic patterns here, one line each |
| `src/yxroute.{cpp,hpp}` | `routing_function = yx` — YX dimension-order (T2 deadlock work) |
| `src/snakeroute.{cpp,hpp}` | `routing_function = snake` — Hamiltonian broadcast route (prefix multicast) |
| `src/matrixtraffic.{cpp,hpp}` | `traffic = matrix(<file>)` — drive BookSim from a Timeloop traffic matrix |

Edits to upstream files (the cross-cutting ones — what used to be `multicast.patch`):

| File | Change | Config knob |
|---|---|---|
| `src/flit.{cpp,hpp}` | `mcast` flag + `mcast_copies` list on the Flit | — |
| `src/routers/iq_router.cpp` | eject-copy **fork** in switch traversal | — |
| `src/booksim_config.cpp` | register the knobs below | — |
| `src/trafficmanager.{cpp,hpp}` | multicast / broadcast / column-reduce injection | `mcast_k`, `mcast_naive`, `reduce_col`, `bcast_all` |
| `src/traffic.cpp`, `src/routefunc.cpp` | factory redirects into `veritx_ext` (the hook) | — |

Knobs: `mcast_k=<g>` (row-multicast fold), `bcast_all={1,2}` (1 = snake broadcast to all
cores, 2 = naive N−1 unicast baseline), `reduce_col=1` (column-reduce partials),
`mcast_naive=1` (unicast baseline for the multicast comparison).

## Gotchas

- **BookSim exits 255 on success** — its exit code is meaningless. Read success from
  stdout (a finite `Packet latency average`), as the scripts and `veritx-rebuild.sh` do.
- **BookSim appends the topology to `routing_function`** — `routing_function = yx;` on a
  mesh looks up key `yx_mesh`. Passing `yx_mesh` looks up `yx_mesh_mesh` and aborts.
- **`bcast_all` requires `packet_size = 1`** (single-flit deliveries); it errors otherwise.
- **`/opt` is not persistent** — `make shell` is `--rm`. Edit here in the repo (mounted),
  let `veritx-rebuild.sh` push into `/opt` and build.

*(The pre-subtree apparatus — patches, `build.sh`, the mirrored `src/` overlay — is kept
for reference under `archive/booksim-ext/`.)*
