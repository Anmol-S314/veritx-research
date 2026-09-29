# Topology synthesis — decisions

Extracted from `veritx_dse/synthesis/*`.

## RHO / GRPO (`iterative_synthesizer.py`, `rho_grpo_adapter.py`)

Rolling Horizon Optimization and Group Relative Policy Optimization start from a
seed topology and iteratively improve via BookSim trace replay.

- **RHO**: at each step, sample `B` candidate mutations; roll each forward `H`
  steps with random rollouts; keep the candidate whose best rollout latency is
  lowest.
- **GRPO**: at each step, sample a group of `G` candidates, evaluate all with
  BookSim, compute the group baseline (mean reward), and pick the best with
  advantage > 0.

`rho_grpo_adapter.py` is the product wiring; `iterative_synthesizer.py` is the
standalone research driver. They must not diverge on the search semantics.

CLI (research driver):

```
python3 iterative_synthesizer.py --trace runs/traces/qwen3_serving_16rank.trace \
  --method rho --steps 50 --horizon 5 --branch 5
python3 iterative_synthesizer.py --trace ... --method grpo --steps 50 --group 4
```

## MILP / SA (`candidate.py`, `milp_topology_v2.py`)

- The TMCF MILP always minimizes traffic-weighted hops; it cannot express
  `objective` / `pipe_cost` / `wire_cost`. Those are consumed **only** by the
  simulated-annealing path (`sa_geodesic`), used above the exact-solve cap
  (`defn.nodes > defn.max_nodes`).
- The SA seed is `layout_seed`, so the same definition yields the same graph
  every time — a synthesis candidate is a stable scientific identity, never a
  function of wall-clock.
- SA has no optimality proof: its status is `FEASIBLE`, never promoted to
  `OPTIMAL`.
- A solver exception yields `status="FAILED"` with no links — never a partial
  graph.

## Bayesian optimization (`bo_synthesizer.py`, `bo_adapter.py`)

`gp_minimize` (scikit-optimize) over the design space; the adapter exposes it to
the product study runner.

## Known leftover

`synthesis/iterative_synthesizer.py:edges_of` was defined twice (the first
returning an empty set, with an authoring note left in the source). The dead
first definition has been removed; keep only one.
