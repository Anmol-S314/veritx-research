# VERITX Reproducibility (C8 / R4)

A clean machine must build VERITX from an exact release commit and reproduce
the science. Current state: **release environment pinned enough for a frozen
RC; OS packages are recorded, not bit-reproducible**.

## What is pinned

| artifact | pin | mechanism |
|----------|-----|-----------|
| source | exact git SHA | `prod/production-readiness` commits |
| container base | `ubuntu:22.04@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02` | `Dockerfile` `ARG UBUNTU_IMAGE` (R4.1) |
| release container | `VERITX_TOOLS_IMAGE` digest | workflow fails a tag release unless `@sha256:` is present |
| Docker external clones | immutable commits | Accelergy / Yosys / SymbiYosys / CBMC `git fetch <sha>`; Timeloop `git clone` + `git checkout <sha>`; submodules follow the pinned superproject gitlinks |
| BookSim source | vendored in-repo | tracked `third_party/booksim2` |
| ASTRA source | vendored in-repo | tracked `third_party/astra-sim` |
| Ramulator source | vendored in-repo | tracked `third_party/ramulator2` |
| Python deps | declared | `tracks/t3-topology/dse/requirements.lock` (sha256 captured into run provenance) |
| Python floor | 3.10 declared / enforced | `pyproject` + `assert_runtime_compatible` |
| compiler | `RELEASE_CXX` (default g++) | top-level `Makefile` (C1.5) |
| BookSim binary | build manifest (rev/dirty/sha/size/compiler/recipe) | `make release-build` |
| ASTRA binary | build manifest | `make release-build` |
| backend evidence | binds manifest sha + recipe + route dump | `backend/evidence.py` v3 |

`scripts/check_dockerfile_pins.py` fails if any `FROM` is not digest-pinned or
any `git clone` is not pinned by commit/tag; the clean-clone job runs it.

## R4.4 — bit-reproducibility classification

BookSim binaries built from the same source in two different directories are
**not** bit-identical. The classification is
`SCIENTIFICALLY_EQUIVALENT_NON_BIT_REPRODUCIBLE`, proven by
`scripts/classify_binary_reproducibility.py`:

| build | sha256 | size | `.text` sha256 |
|-------|--------|------|----------------|
| `/tmp/opencode/bsbuild-a` | `373977aa…` | 20,832,472 | `1d43a114…` |
| `/tmp/opencode/bsbuild-bbbbbbbb` | `b3d26405…` | 20,832,480 | `1d43a114…` |

- The executable `.text` section is **byte-identical**; the `.comment`
  compiler string is identical (GCC 15.2.0).
- The bytes differ only in build metadata: the embedded absolute build path
  (DWARF debug info, from `-g`) and the GNU build-id derived from it.

Classification rule: bit-identical is not required unless the project
certifies reproducible builds. It does not, so this is not a release blocker;
each build's manifest binds its own binary sha, and scientific identity is
asserted separately (repeat-run evidence-id equality).

## R4.3 — package drift

A bit-reproducible OS environment is **not** claimed. The practical
first-release claim is:

- the release container is pinned by digest;
- tool and source revisions are recorded (`.comment`, git SHAs, build
  manifests);
- each backend binary's SHA is recorded in its build manifest and bound into
  backend evidence.

`apt`/`pip` are not pinned to a snapshot; `apt-get update` and
`pip3 install` resolve current packages at image build time. This is recorded
here rather than overclaimed.

## Clean-clone qualification

Run at `c759b84b` (build + fast tier + harness green; see
`PRODUCTION-SEAL.md` §12) and owned by the T6 `clean-clone` workflow job,
which now also runs the Studio contract suite and asserts the clean tree.

## Partial reproducibility already proven

- `make release-build` builds BookSim/ASTRA/Ramulator from tracked source on
  the host and writes build-time manifests; the manifest is verified against
  the binary at execution (sha256 + size) and its recipe is admitted per
  certified profile.
- Persisted evidence is content-addressed and refuses a rehashed impossible
  document; run identity excludes timestamps where the science is
  deterministic (repeat BookSim runs assert identical `evidence_id`).
