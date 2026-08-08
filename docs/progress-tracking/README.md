# T3 Progress Tracking — extracted from Google Drive

Source: Google Drive folder "Training Docs"
(`https://drive.google.com/drive/folders/1qQ5HO4qM2ZIMwc_9uLLrkxj_JTbzjmGP`)
Extracted: 2026-08-03

## Checklists (Google Sheets → CSV)

| File | Owner | Progress (as listed in sheet) |
|---|---|---|
| `1_Timeloop_Traffic_Matrix_Checklist.csv` | Pair A (Abhishek + Shourayadip) | 4/23 done (17.4%), TM-05 in progress |
| `2_Pareto_Analysis_Infra_Checklist.csv` | Manal + Adhitya (Pair B support) | 0/29 done (0%) — NOTE: stale vs branch `pareto-analysis-manal`, which already has analysis.py/aggregate.py/plot_curves.py committed |
| `3_Custom_Topology_Differentiators_Checklist.csv` | Pair B (Sowmith + Shouryadip) | 2/26 done (7.7%), CT-03 in progress — NOTE: PDFs show CT-05/06/07/08 also done, sheet not updated |

## Topology Study folder (Google Drive → PDF → TXT)

| File | What it covers | Status per content |
|---|---|---|
| `TM-02_03_Setup` | What problem/arch/mapper YAMLs control; loop nest, mapspace, mapper concepts | Complete |
| `Spatial_Model` | Design of the real attention spatial model: 16 tiles / 32 heads (2 heads per tile), tensor table for LLaMA-2 7B (qkv/attention/out_proj/gate_up/down_proj) | Design decided (checklist TM-05 = in progress) |
| `Custom_Topology_Progress` | CT-01..CT-08: baseline sweep results (fly4, mesh4x4, torus4x4, fattree16, flatfly16 ± knc/ugal, cmesh16), torus dim_order deadlock analysis, dragonfly no-go (72-node min), anynet verified + converter | CT-01–08 done per PDF, checklist not updated |
| `flatfly_and_ftree` | FlatFly + FatTree topology study notes (arch, routing, tradeoffs) | Complete |
| `Dragonfly_and_KNCube` | Dragonfly + Mesh/Torus (KNCube) study notes, formulas, deadlock/VC | Complete |

## Key facts for the repo work

- Dragonfly is a confirmed **no-go at 16 nodes** (72 min, needs 72×72 matrix) — matches the
  pareto branch's all-`no_output` dragonfly16 rows.
- Torus requires `dim_order` (not `dor`) — the deadlock pitfall found in both the student
  PDFs and `booksim-subtree-migration` PITFALLS.md.
- The pareto branch's committed sweep data (aggregate.csv) is the same baseline dataset
  as `Custom_Topology_Progress.pdf` (fly4/mesh4x4/torus4x4/fattree16/flatfly16/cmesh16 @
  rates 0.002–0.03, saturation ~0.03).
- Checklists still point at `github.com/Anmol-S314/veritx-research` paths — predates the
  internal datavex registry migration.
