"""Shared builders for Wave-F optimization tests.

Single source of fixtures so E2E and adversarial tests forge REAL
artifacts produced by the REAL control plane (§152: adversarial tests
construct valid alternative parents, never ``assert x == x``).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
DSE = TESTS.parent
if str(DSE) not in sys.path:
    sys.path.insert(0, str(DSE))

from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402

METRICS = ["sim.latency.avg_cycles", "sim.delivered.packets",
           "sim.flits.injected"]


def make_cp(tmp: Path):
    """A control plane over a clean store + clean provenance repo +
    the real BookSim binary (skips when unavailable)."""
    git = tmp / "cleanrepo"
    git.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(git), *args], check=True,
                       capture_output=True, timeout=30)
    (git / "src.txt").write_text("v1")
    subprocess.run(["git", "-C", str(git), "add", "src.txt"], check=True,
                   capture_output=True, timeout=30)
    subprocess.run(["git", "-C", str(git), "commit", "-qm", "v1"],
                   check=True, capture_output=True, timeout=30)
    from veritx_dse.simulation.booksim import find_booksim_bin
    try:
        binary = Path(find_booksim_bin(REPO))
    except FileNotFoundError:
        pytest_skip = __import__("pytest").skip
        pytest_skip("no runnable BookSim binary")
    return SrotaControlPlane(store_root=tmp / "store", repo_root=git,
                             binary=binary)


def we_workload(op_ids, compute_ms: int = 1):
    """Temporal overlay: one network window + a compute tail (§8)."""
    from veritx_dse.wavee.model import (
        ClockDef, ResourceDef, WaveEPerformanceModel,
    )
    from veritx_dse.wavee.time import QTime
    from veritx_dse.wavee.workload import (
        EVENT_NETWORK_TRAFFIC_WINDOW, WaveETemporalEvent,
        WaveETemporalWorkload,
    )
    model = WaveEPerformanceModel(
        clocks=(ClockDef("net", 10 ** 9),),
        resources=(ResourceDef("gpu.compute", "EXCLUSIVE", capacity=1),),
        network_clock="net")
    return WaveETemporalWorkload(
        performance_model=model,
        events=(
            WaveETemporalEvent("NET", EVENT_NETWORK_TRAFFIC_WINDOW,
                               QTime(0), phase="DECODE", rank=0),
            WaveETemporalEvent("TAIL", "COMPUTE", QTime(compute_ms, 1000),
                               "gpu.compute", deps=("NET",),
                               phase="DECODE", rank=0),
        ),
        wave_d_operation_ids=tuple(op_ids))


def scenario_intent(*, name: str, phase: str = "DECODE", tp: int = 1,
                    dp: int = 4, wave_e=None, seed: int = 7
                    ) -> dict:
    """One canonical Wave-D scenario intent (+ optional Wave-E overlay).

    The multicast fanned out to dp-1 destinations gives the fabric
    dimension real work to do at tiny scale.
    """
    intent = {
        "schema_version": 1, "name": name, "fabric_preset": "mesh4",
        "fabric_overrides": {"workload.tp": tp, "workload.pp": 1,
                             "workload.ep": 1, "workload.dp": dp},
        "workload": {"wave_d": {
            "parallelism": {"tp": tp, "pp": 1, "ep": 1, "dp": dp},
            "semantics": {"phase": phase},
            "operations": [mc_operation(dp, phase)],
        }},
        "backend_target": "BOOKSIM_STANDALONE", "seed": seed,
        "metrics": list(METRICS), "timeout_s": 120,
    }
    if wave_e is not None:
        intent["workload"]["wave_e"] = wave_e.to_dict()
    return intent


def mc_operation(dp: int, phase: str = "DECODE") -> dict:
    """One source-replicated multicast to dp-1 destinations."""
    return {
        "operation_id": "m0", "kind": "MULTICAST", "owner": 0,
        "phase": phase, "step": 0, "deps": [],
        "detail": {"multicast_id": "m0", "source_rank": 0,
                   "destinations": list(range(1, dp)),
                   "payload_bytes": 65536,
                   "replication": "SOURCE_REPLICATION"}}


def opt_doc(*, name: str = "wavef-opt",
            scenarios: tuple[str, ...] = ("decode",),
            phases: dict[str, str] | None = None,
            objectives: list[dict] | None = None,
            hard_constraints: list[dict] | None = None,
            search_policy: str = "EXHAUSTIVE_GRID",
            budget: dict | None = None,
            selection_policy: str = "SINGLE_OBJECTIVE",
            tp_values: list[int] | None = None,
            topology_values: list[str] | None = None,
            width_values: list[int] | None = None,
            wave_e: bool = True) -> dict:
    """A Wave-F OptimizationRequest over the canonical scenario(s).

    Default space: topology {mesh, torus} x link_width {64, 128} —
    every value verified to lower + execute through the sealed chain.
    """
    phases = phases or {s: ("DECODE" if s != "prefill" else "PREFILL")
                        for s in scenarios}
    we = we_workload(("m0",)) if wave_e else None
    intent = {
        s: scenario_intent(name=f"wavef-{s}", phase=phases[s],
                           wave_e=we)
        for s in scenarios}
    doc = {
        "name": name,
        "scenarios": [{"name": s, "intent": intent[s]}
                      for s in scenarios],
        "parameters": [
            {"name": "fabric.topology",
             "values": topology_values or ["mesh", "torus"]},
            {"name": "fabric.link_width",
             "values": width_values or [64, 128]},
        ],
        "objectives": objectives or [
            {"metric": "system.makespan_s", "direction": "MINIMIZE",
             "scenario": scenarios[0]}],
        "hard_constraints": hard_constraints or [],
        "search_policy": search_policy,
        "selection_policy": selection_policy,
    }
    if budget:
        doc["budget"] = budget
    return doc
