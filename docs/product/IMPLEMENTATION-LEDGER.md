# IMPLEMENTATION-LEDGER

Append-only record of implementation against the frozen planning corpus.
No architectural prose — see the planning documents.

## Baseline

| Field | Value |
|---|---|
| Branch | `integration/studio-reconciliation` |
| HEAD | `914d65db42fcfaaabbb9f4fa02cb7f155434ef36` |
| HEAD subject | `studio-serving: namespace discipline + ownership boundary; evaluate flow rail` |
| HEAD date | 2026-09-25 20:28:18 +0530 |
| Worktree at start | **DIRTY** — 55 entries (pre-existing serving work + untracked planning corpus) |

### Baseline failures (pre-existing, NOT fixed in this program)

| Command | Result |
|---|---|
| `python3 -m pytest tests/` (dse) | **3833 passed, 17 skipped** |
| `python3 -m pytest tests/` (studio) | **2 failed, 8 passed, 1 skipped** |
| `npx tsc --noEmit` (studio) | **exit 0** |
| `python3 scripts/validate_fixtures.py` | exit 0 (fast path) |
| `python3 scripts/check_intent_ontology.py` | exit 0 — `348 rows, 59 declared fields covered, all evidence=V` |
| capability registry checker | **did not exist** |
| exposure registry checker | **did not exist** |

Pre-existing studio failures (attributed to the uncommitted serving work at
baseline, outside this program's scope):

- `tests/test_studio_contract_v2.py::test_provisioned_validator_proves_backend_fixtures_through_engine`
- `tests/test_studio_contract_v2.py::test_fresh_provisioned_regeneration_bytes`
  — fixture regeneration digest mismatch on `evaluated-design`
  (`raw_evidence_digest`, `performance_result_id`, `backend_producer.producer_identity`).

### Planning artifact versions

| Artifact | Bytes | Authority |
|---|---|---|
| `docs/product/INTENT-ONTOLOGY.md` | 33511 | Gate 1 |
| `docs/product/intent-ontology.yaml` | 301905 | Gate 1 — 348 rows, 59 declared fields |
| `docs/product/CROSS-DOMAIN-LAWS.md` | 80761 | Gate 3 |
| `docs/product/CAPABILITY-MATRIX.md` | 43688 | Gate 4 |
| `docs/product/capability-registry.yaml` | 36146 | Gate 4 — 73 rows, 5 envelopes, 11 conditions, `cap-v1` |
| `docs/product/PRODUCT-FLOWS.md` | 88013 | Gate 5 |
| `docs/product/GUIDED-EXPERT.md` | 61571 | Gate 6 |
| `docs/product/exposure-registry.yaml` | 14462 | Gate 6 — 69 rows, 10 classes, 6 presets |
| `docs/product/DESIGN-REVIEW.md` | 40470 | Gate 7 |
| `docs/product/STUDIO-WIREFRAMES.md` | 163514 | Gate 8 |
| `docs/product/INTENT-*.md` | ×12 | Gate 2 |

Planning corpus is **immutable** during implementation.

## Slices

| # | Slice | Commit | Status |
|---|---|---|---|
| 1 | remove false v4 controls and claims | `studio: remove false v4 controls and claims` | see below |
| 2 | validate capability and exposure registries | `product: validate capability and exposure registries` | see below |
| 3 | canonical normalization + capability semantics version | `product: canonical arbitration identity + capability semantics version` | see below |
| 4 | DesignViewV2 contract | `product: add DesignViewV2 contract` | see below |
| 5 | structured readiness and findings | `product: add structured design readiness and findings` | see below |
| 6 | bind review compile to draft design hash | `product: bind review compile to draft design hash` | see below |
| 7 | rebuild design editor on DesignViewV2 | `studio: rebuild design editor on DesignViewV2` | see below |
| 8 | canonical review flow | `studio: add canonical review flow` | see below |
| 9 | reconcile compile result handoff | `studio: reconcile compile result handoff` | see below |

## Files changed

_(appended per slice)_

## Contracts implemented

_(appended per slice — exact planning/debt IDs)_

## Removals

_(appended per slice)_

## Test results

_(appended per slice — exact commands and counts)_

## Known blockers

_(appended per slice — with debt IDs)_

## Debt references

Referenced, never duplicated: PF-D1…PF-D16, GX-D1…GX-D8, CAP-D1…CAP-D5,
XDOM-D1…XDOM-D8, REV-D1…REV-D7, MEM-D1/D3/D4, MEM-EVAL-D1/D2, MEM-METRIC-D1,
OPT-D2/D3/D5/D6/D7/D8, FAB-D1/D4/D6, VC-D1, COMM-D1, ROUTER-D2.

## Contract conflicts

_(appended only if `IMPLEMENTATION-CONTRACT-CONFLICT` is raised)_
