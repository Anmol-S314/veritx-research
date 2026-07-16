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

## Try it — a 2-minute worked example

Prove the whole loop with a throwaway edit (we undo it at the end). Inside `make shell`:

**1. Edit a real file.** Add one line to `src/main.cpp`, just after `int main(...)`'s `{`:

```cpp
int main( int argc, char **argv )
{
  cerr << "[hello from my build]" << endl;   // <-- add this line

  BookSimConfig config;
```

**2. Rebuild:**

```bash
third_party/booksim2/veritx-rebuild.sh
```

**3. Run any example and look for your line:**

```bash
booksim /opt/booksim2/src/examples/mesh88_lat sim_count=1 2>&1 | grep hello
# -> [hello from my build]
```

Your edit is in the binary — that's the whole point.

**4. See just your change** (BookSim's original is the baseline, so only your line shows):

```bash
git diff third_party/booksim2/src/main.cpp    # one +line
```

**5. Undo it** (it was only a demo — a real change you'd keep and `git commit`):

```bash
git checkout -- third_party/booksim2/src/main.cpp
```

That's the entire workflow: **edit a real file → one rebuild command → it's live.** A real
change (a new routing function, a router tweak) is the same five steps minus the undo.

## Worked example: add a routing function

This is the real pattern — how `yx` and `snake` were added. Adding a routing function is
**three touch points**: a new file pair, one line in the hook, one line in your `.cfg`.
Copy `src/yxroute.{cpp,hpp}` as your template.

**1. New file `src/myroute.hpp`** — declare the function (signature is fixed by BookSim):

```cpp
#ifndef _MYROUTE_HPP_
#define _MYROUTE_HPP_
#include "routefunc.hpp"
void my_mesh(const Router *r, const Flit *f, int in_channel,
             OutputSet *outputs, bool inject);
#endif
```

**2. New file `src/myroute.cpp`** — the logic. Pick the output port, set the VC range,
emit it. The VC block is boilerplate every route needs — lift it verbatim from
`yxroute.cpp`; only the `out_port` line is yours:

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

**3. Register it — one line in `src/veritx_ext.cpp`** (the *only* wiring you touch):

```cpp
#include "myroute.hpp"           // top of file, next to the other route includes
// ... inside VeritXRegisterRouting():
gRoutingFunctionMap["my_mesh"] = &my_mesh;
```

> ⚠️ Key is `my_mesh` (name **+ topology**). BookSim appends the topology, so `.cfg` says
> `routing_function = my;` on a mesh. Register `my` and it looks up `my_mesh_mesh` → abort.
> See Gotchas.

**4. Select it in a `.cfg`** (e.g. `configs/mesh8x8.cfg`):

```
routing_function = my;
```

**5. Rebuild and run:**

```bash
third_party/booksim2/veritx-rebuild.sh
booksim tracks/t3-topology/configs/mesh8x8.cfg
```

No Makefile edit (the `*.cpp` glob picks up `myroute.cpp`), no patch, no core-file edit.

**Traffic patterns** are the same shape, one file over: implement a `TrafficPattern`
subclass (see `matrixtraffic.cpp`), then add an `if (name == "mine")` branch in
`VeritXNewTraffic()` instead of a map line. Select with `traffic = mine(<args>);`.

**Multicast is different — it's not a hook add.** `mcast`/`bcast_all`/`reduce_col` are
*cross-cutting* edits to upstream files (the flit carries a copy-list, `iq_router.cpp`
forks it, `trafficmanager.cpp` injects it) — see the delta table under
[What VeritX added](#what-veritx-added-the-delta). You drive it from a `.cfg` with the
knobs (`mcast_k`, `bcast_all=1`, …), not by registering a function. If you need to *change*
multicast behaviour you edit those real files directly; that's exactly what the subtree
buys you.

## Does my change persist?

Two different things, and they persist differently — worth knowing so an edit doesn't
seem to "disappear":

| What | Lives in | Persists? |
|---|---|---|
| your **source edit** (`third_party/booksim2/src/…`) | the repo (mounted at `/workspace`, in git) | ✅ yes — on your disk |
| the **rebuilt binary** (`veritx-rebuild.sh` → `/opt`, `/usr/local/bin/booksim`) | the container's throwaway layer | ❌ no — `make shell` is `--rm` |

So `veritx-rebuild.sh` gives you a working `booksim` **for that session only** — the fast
edit/test loop. Exit the shell and `/opt/booksim2` snaps back to whatever the *image* was
built with. To make a change **permanent in the image**, rebuild it:

```bash
make image-build      # COPYs third_party/booksim2 and compiles it into the image
```

Or just commit + push: CI watches `third_party/booksim2/**` and rebuilds the image for
you. Full loop: **edit (persists in git) → `veritx-rebuild.sh` (session, to test) → commit
→ image rebuild (permanent).** Only an *uncommitted* edit is ever session-only.

## See exactly what we changed

```bash
git log  --oneline -- third_party/booksim2      # the squashed import, then our edits
git diff <import-commit> -- third_party/booksim2 # our full delta vs pristine upstream
```

Our delta is small and legible — that's the payoff of a subtree over a full-file overlay.

## Bumping BookSim to a new upstream version

A version bump is a **normal git merge**, not a patch-reject or a silent shadow:

```bash
third_party/booksim2/veritx-bump.sh <new-commit-or-tag>
```

`veritx-bump.sh` wraps `git subtree pull` with the prefix, upstream URL, and `--squash`
baked in, and runs from the repo root for you. Under the hood it's just:
`git subtree pull --prefix third_party/booksim2 <url> <ref> --squash`.

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
