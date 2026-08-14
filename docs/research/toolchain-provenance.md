# Toolchain Provenance — third_party checkouts kept OUT of the monorepo

## PyTorchSim (`third_party/pytorchsim/`)

**Decision (2026-08-14):** kept out of the monorepo — gitignored
(`third_party/pytorchsim/` in `.gitignore`). Rationale: it is a large upstream
toolchain (PyTorch → TOGSim → BookSim2 + Ramulator2) with its own build; the
monorepo vendors only what it patches (booksim2, via git subtree).

**Pin (the reproducibility answer):**
- Checkout: `third_party/pytorchsim/` (local disk)
- HEAD: `509f42554202edb29cf8d31ddf619776f465e717` — "Update tutorial link and add setup guide reference" (2026-05-11)
- Role: the T3 prefill/decode workload source (FINDINGS.md tables: PyTorchSim → TOGSim → BookSim2 + Ramulator2)

**Reproduce:** `cd third_party/pytorchsim && git checkout 509f425` then follow its build steps. The results in `tracks/t3-topology/results/*.log` were produced from this checkout.

**Status:** 2026-08-14 — checkout verified present with the pinned HEAD (Steve, seed 73f3). If the checkout is ever lost, re-clone and pin to the commit above; the pinned commit is the reproducibility contract.

## Booksim2 (`third_party/booksim2/`)

Vendored in-repo via git subtree (see `third_party/booksim2/VERITX.md`) — tracked, pinned upstream + VeritX edits.

## History

- 2026-08-14: pytorchsim pin documented (was: untracked + absent from Dockerfile + no pin anywhere — seed 73f3).
