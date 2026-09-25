# VERITX Reproducibility (C8)

A clean machine must build VERITX from an exact release commit and
reproduce the science. Current state: **partial**. The release is **not
ready** on this axis.

## What is pinned today

| artifact | pin | mechanism |
|----------|-----|-----------|
| source | exact git SHA | `prod/production-readiness` commits |
| BookSim source | vendored in-repo | tracked `third_party/booksim2` |
| ASTRA source | vendored in-repo | tracked `third_party/astra-sim` |
| Ramulator source | vendored in-repo | tracked `third_party/ramulator2` |
| Python deps | declared | `tracks/t3-topology/dse/requirements.lock` (sha256 captured into run provenance) |
| Python floor | 3.10 declared / enforced | `pyproject` + `assert_runtime_compatible` |
| compiler | `RELEASE_CXX` (default g++) | top-level `Makefile` (C1.5) |
| BookSim binary | build manifest (rev/dirty/sha/size/compiler/recipe) | `make release-build` |
| ASTRA binary | build manifest | `make release-build` |
| backend evidence | binds manifest sha + recipe + route dump | `backend/evidence.py` v3 |

## What is still moving (blocks C8)

1. **Container image is a moving tag in the release path.** The workflow
   defaults to `ghcr.io/anmol-s314/veritx-tools-base:latest` unless the
   repository variable `VERITX_TOOLS_IMAGE` is set to an immutable digest;
   a tag-release job now FAILS unless the image is `@sha256:` pinned. The
   default must still be replaced by a digest for a real release.
2. **Docker external clones are now pinned by commit** (Accelergy, Yosys,
   SymbiYosys, CBMC; Timeloop was already pinned). `scripts/check_dockerfile_pins.py`
   fails if any `git clone` in the release image path is unpinned, and the
   clean-clone job runs it. Remaining: the base image (`ubuntu:22.04`) and
   apt package set are not digest-pinned.
3. **No `release-manifest.json` was owed** — now produced by
   `make release-manifest-json`, binding the release SHA, container image +
   digest-pin state, backend manifests, schema versions, tool versions and
   validation-report digests.
4. **Clean-clone qualification** was run at `c759b84b` (build + fast tier +
   harness green; see `PRODUCTION-SEAL.md` §12).

## Owed (C8)

- Pin the container by digest; pin every external Docker source by commit.
- Generate `release-manifest.json` at release time.
- Run the T6 clean-clone job (already sketched in `release.yml`) against the
  RC SHA and record the result in `PRODUCTION-SEAL.md` and
  `docs/production/REPRODUCIBILITY.md`.
- Re-run the live-backend tier at the exact RC SHA.

## Partial reproducibility already proven

- `make release-build` builds BookSim/ASTRA/Ramulator from tracked source on
  the host and writes build-time manifests; the manifest is verified against
  the binary at execution (sha256 + size) and its recipe is admitted per
  certified profile.
- Persisted evidence is content-addressed and refuses a rehashed impossible
  document; run identity excludes timestamps where the science is
  deterministic (repeat BookSim runs assert identical `evidence_id`).
