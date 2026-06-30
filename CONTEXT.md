# VeritX Infrastructure Context

## Engagement Model
- **Partner**: VeritX BTech Research Programme (AI-native NoC architecture)
- **Relationship**: Research partnership — we host infrastructure on our self-hosted GitLab
- **Access**: 15 students get individual GitLab accounts

## Resolved Terms

| Term | Definition |
|------|------------|
| VeritX | BTech 6-month research programme, 4 tracks (T1-T4), AI-native NoC |
| T1 | KVCache QoS + gem5/Garnet/ASTRA-sim (4 students, heavy compute) |
| T2 | Deadlock with Booksim 2.0 (4 students, lightweight) |
| T3 | Topology with Booksim + Timeloop + Accelergy (4 students, medium) |
| T4 | Formal verification with SymbiYosys + Yosys + CBMC (3 students, variable) |
| Infrastructure monorepo | `veritx-research` — single GitLab repo, 5 CI matrix cells |
| Self-hosted runner | Docker executor on 32GB+ server/VM |
| Container runtime | Docker (not Podman) — best GitLab CI integration |
| Base OS | Ubuntu 22.04 LTS (all tools require POSIX) |
| Gem5 build strategy | Pre-built in multi-stage Docker image, pushed to GitLab registry |
| CI pipeline | build → lint → test → sim → report |
| EDA flow | Booksim/Timeloop/gem5 sims run inside Docker container in CI |
| Ticket/issue tracker | GitLab Issues (not GitHub) |
| Branch model | Feature branches per experiment, MR → main with CI gate |
