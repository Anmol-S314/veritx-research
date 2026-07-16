# Working on BookSim (vendored)

BookSim 2.0, vendored as a **git subtree** — pinned upstream (`booksim/booksim2` @
`28f43299`) with VeritX's edits as ordinary commits on top. You edit the real `.cpp`
files: full LSP, normal git, no patch to hand-write. `git diff` is our exact delta from
upstream; a version bump is a normal merge.

---

## Edit → rebuild loop

```bash
make shell                                   # from the repo root
# edit any file under third_party/booksim2/src/
third_party/booksim2/veritx-rebuild.sh       # sync → compile → install → verify
```

`veritx-rebuild.sh` compiles incrementally (a one-file change is seconds), installs
`/usr/local/bin/booksim`, and verifies the multicast still forks — a build that dropped
our edits fails the check. T3's scripts call it automatically if the `booksim` on `PATH`
lacks our extensions.

Sanity-check the loop: add `cerr << "hi" << endl;` at the top of `main()` in
`src/main.cpp`, rebuild, run any example, `grep hi` the output — then
`git checkout -- src/main.cpp`.

## Worked example: add a routing function

How `yx` and `snake` were added. **Three touch points:** a new file pair, one line in the
hook, one line in your `.cfg`. Copy `src/yxroute.{cpp,hpp}` as your template.

**1. `src/myroute.hpp`** — declare it (signature is fixed by BookSim):

```cpp
#ifndef _MYROUTE_HPP_
#define _MYROUTE_HPP_
#include "routefunc.hpp"
void my_mesh(const Router *r, const Flit *f, int in_channel,
             OutputSet *outputs, bool inject);
#endif
```

**2. `src/myroute.cpp`** — pick the output port, set the VC range, emit it. The VC block
is boilerplate; lift it verbatim from `yxroute.cpp` — only `out_port` is yours:

```cpp
#include "myroute.hpp"
#include "globals.hpp"

void my_mesh(const Router *r, const Flit *f, int in_channel,
             OutputSet *outputs, bool inject)
{
  int out_port = inject ? -1 : /* your next-hop from r->GetID() to f->dest */;

  int vcBegin = 0, vcEnd = gNumVCs - 1;   // (+ the READ/WRITE_REQUEST/REPLY block from yxroute.cpp)
  outputs->Clear();
  outputs->AddRange(out_port, vcBegin, vcEnd);
}
```

**3. Register — one line in `src/veritx_ext.cpp`** (the only wiring you touch):

```cpp
#include "myroute.hpp"                          // with the other route includes
gRoutingFunctionMap["my_mesh"] = &my_mesh;      // inside VeritXRegisterRouting()
```

**4. Select in a `.cfg`:** `routing_function = my;` **5. Rebuild + run:**

```bash
third_party/booksim2/veritx-rebuild.sh
booksim tracks/t3-topology/configs/mesh8x8.cfg
```

No Makefile edit (the `*.cpp` glob picks up `myroute.cpp`), no patch, no core-file edit.

> ⚠️ Key is `my_mesh` (name **+ topology**). BookSim appends the topology, so the `.cfg`
> uses `my`. Register `my` and it looks up `my_mesh_mesh` → abort (see Gotchas).

**Traffic patterns** — same shape, one file over: subclass `TrafficPattern` (see
`matrixtraffic.cpp`), add an `if (name == "mine")` branch in `VeritXNewTraffic()` instead
of a map line, select with `traffic = mine(<args>);`.

**Multicast is not a hook add.** `mcast`/`bcast_all`/`reduce_col` are cross-cutting edits
to upstream files (the flit carries a copy-list, `iq_router.cpp` forks it,
`trafficmanager.cpp` injects it) — see the delta table below. Drive it from a `.cfg` with
the knobs; to change its behaviour, edit those files directly.

## Does my change persist?

| What | Lives in | Persists? |
|---|---|---|
| **source edit** (`src/…`) | the repo (mounted, in git) | ✅ on your disk |
| **rebuilt binary** (`/opt`, `/usr/local/bin/booksim`) | container's throwaway layer | ❌ `make shell` is `--rm` |

`veritx-rebuild.sh` gives a working `booksim` **for that session only**. To bake a change
into the image:

```bash
make image-build      # COPYs third_party/booksim2 and compiles it in
```

Or commit + push — CI watches `third_party/booksim2/**` and rebuilds the image. Only an
*uncommitted* edit is session-only.

## Bumping BookSim to a new upstream version

A normal git merge:

```bash
third_party/booksim2/veritx-bump.sh <new-commit-or-tag>
# = git subtree pull --prefix third_party/booksim2 <url> <ref> --squash
```

Files we didn't touch auto-merge; lines near ours conflict in a real `.cpp` with full
context. Commit the merge, update the pinned commit at the top of this file, then
`veritx-rebuild.sh` and rerun the T3 gates.

See our delta: `git log --oneline -- third_party/booksim2`, or
`git diff <import-commit> -- third_party/booksim2`.

---

## What VeritX added (the delta)

New files (`*.cpp */*.cpp` glob → they just compile in):

| File | Adds |
|---|---|
| `src/veritx_ext.{cpp,hpp}` | factory hook — register routing fns / traffic patterns, one line each |
| `src/yxroute.{cpp,hpp}` | `routing_function = yx` — YX dimension-order (T2 deadlock work) |
| `src/snakeroute.{cpp,hpp}` | `routing_function = snake` — Hamiltonian broadcast (prefix multicast) |
| `src/matrixtraffic.{cpp,hpp}` | `traffic = matrix(<file>)` — drive BookSim from a Timeloop matrix |

Edits to upstream files (the cross-cutting ones — the old `multicast.patch`):

| File | Change | Config knob |
|---|---|---|
| `src/flit.{cpp,hpp}` | `mcast` flag + `mcast_copies` list on the Flit | — |
| `src/routers/iq_router.cpp` | eject-copy **fork** in switch traversal | — |
| `src/booksim_config.cpp` | register the knobs below | — |
| `src/trafficmanager.{cpp,hpp}` | multicast / broadcast / column-reduce injection | `mcast_k`, `mcast_naive`, `reduce_col`, `bcast_all` |
| `src/traffic.cpp`, `src/routefunc.cpp` | factory redirects into `veritx_ext` | — |

Knobs: `mcast_k=<g>` (row-multicast fold), `bcast_all={1,2}` (1 = snake broadcast to all
cores, 2 = naive N−1 unicast baseline), `reduce_col=1` (column-reduce partials),
`mcast_naive=1` (unicast baseline).

## Gotchas

- **BookSim exits 255 on success** — exit code is meaningless. Read success from stdout
  (a finite `Packet latency average`), as the scripts do.
- **`routing_function` gets the topology appended** — `yx` on a mesh → key `yx_mesh`.
  Passing `yx_mesh` → `yx_mesh_mesh` → abort.
- **`bcast_all` requires `packet_size = 1`** (single-flit deliveries); errors otherwise.
- **`/opt` is not persistent** — `make shell` is `--rm`. Edit in the repo (mounted); let
  `veritx-rebuild.sh` push into `/opt`.

*(Pre-subtree apparatus — patches, `build.sh`, the mirrored `src/` overlay — kept under
`archive/booksim-ext/`.)*
