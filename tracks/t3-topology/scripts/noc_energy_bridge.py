#!/usr/bin/env python3
"""Booksim -> Accelergy NoC energy bridge (T3).

Booksim's sweep (results/topology_sweep.json, from run_experiments.py) gives us
real hop counts per topology/injection-rate. Accelergy, given noc_arch.yaml +
noc_ERT.yaml, gives us a calibrated pJ-per-hop coefficient (router traversal +
buffer_read + buffer_write + one link transfer = the energy of moving ONE FLIT
one hop — that 1:1:1:1 action ratio is the standard input-queued VC router
pipeline, not an assumption specific to this bridge). Multiplying hops_avg *
packet_size (flits/packet, read from configs/<topology>.cfg) * pj_per_hop turns
Booksim's per-packet hop count into a real per-packet energy estimate, without
needing Accelergy to understand Booksim's topology at all — it only ever sees
a single, generic "1 hop, 1 flit" action count.

  python3 scripts/noc_energy_bridge.py
  ACCELERGY_BIN=/path/to/accelergy python3 scripts/noc_energy_bridge.py

Writes results/noc_energy.json:
  {
    "pj_per_hop": 5.4,
    "components": {"noc.router": 4.2, "noc.link": 1.2},
    "per_topology": {"mesh4x4": [[rate, hops_avg, energy_pJ], ...], ...},
    "source": "results/accelergy/energy_estimation.yaml"
  }
  where energy_pJ = hops_avg * packet_size * pj_per_hop for that topology's
  configs/<topology>.cfg (defaults to packet_size=1 if the config or the
  packet_size line is missing).

Also writes results/accelergy/ — the actual Accelergy inputs/outputs for this
run (action_counts.yaml, energy_estimation.yaml, ERT.yaml, ART.yaml, the
flattened architecture, and accelergy_run.log), so "pJ_per_hop" is reproducible
and auditable rather than a number that only ever existed inside a tempdir.
"""
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
TRACK = HERE.parent
TIMELOOP = TRACK / "timeloop"

# Follow the same configuration layout as the rest of T3
CONFIG = os.environ.get("CONFIG", "baseline")

RESULTS = TRACK / "results" / CONFIG
ACCELERGY_OUT = RESULTS / "accelergy"

NOC_ARCH = TIMELOOP / "noc_arch.yaml"
NOC_ERT = TIMELOOP / "noc_ert.yaml"

SWEEP = RESULTS / "topology_sweep.json"
OUT = RESULTS / "noc_energy.json"

# One hop = one router traversal + one buffer read + one buffer write (the flit
# moving through the crossbar and its input/output buffers) + one link transfer
# (the wire hop to the next router). This must match the action names in
# noc_ERT.yaml's tables — if you add actions there, add matching counts here.
ONE_HOP_ACTION_COUNTS = {
    "action_counts": {
        "version": 0.2,
        "local": [
            {
                "name": "noc.router",
                "action_counts": [
                    {"name": "traversal", "counts": 1},
                    {"name": "buffer_read", "counts": 1},
                    {"name": "buffer_write", "counts": 1},
                ],
            },
            {
                "name": "noc.link",
                "action_counts": [
                    {"name": "transfer", "counts": 1},
                ],
            },
        ],
    }
}


def _find_noc_ert():
    for name in ("noc_ERT.yaml", "noc_ert.yaml"):
        p = TIMELOOP / name
        if p.exists():
            return p
    return None


def _write_yaml(obj, path):
    """Tiny YAML writer for the one dict shape we emit (avoids a PyYAML dep
    for a single, fixed structure). Falls back to PyYAML if available."""
    try:
        import yaml
        path.write_text(yaml.dump(obj, sort_keys=False))
        return
    except ImportError:
        pass
    lines = ["action_counts:", "  version: 0.2", "  local:"]
    for comp in obj["action_counts"]["local"]:
        lines.append(f"    - name: {comp['name']}")
        lines.append("      action_counts:")
        for a in comp["action_counts"]:
            lines.append(f"        - name: {a['name']}")
            lines.append(f"          counts: {a['counts']}")
    path.write_text("\n".join(lines) + "\n")


def parse_energy_estimation(text: str) -> dict:
    """Parse Accelergy's energy_estimation.yaml. Real schema (Accelergy 0.4):

        energy_estimation:
            version: '0.4'
            components:
              - name: noc.router
                energy: 4.2
              - name: noc.link
                energy: 1.2
            Total: 5.4

    Returns {"total": 5.4, "components": {"noc.router": 4.2, "noc.link": 1.2}}.
    Uses a plain-text parse (not PyYAML) so this also works in minimal envs;
    falls back to PyYAML if present for robustness against reordering.
    """
    try:
        import yaml
        doc = yaml.safe_load(text)["energy_estimation"]
        comps = {c["name"]: float(c["energy"]) for c in doc["components"]}
        return {"total": float(doc["Total"]), "components": comps}
    except ImportError:
        pass
    import re
    comps = {}
    for m in re.finditer(r"-\s*name:\s*(\S+)\s*\n\s*energy:\s*([\d.eE+-]+)", text):
        comps[m.group(1)] = float(m.group(2))
    total_m = re.search(r"^\s*Total:\s*([\d.eE+-]+)", text, re.M)
    total = float(total_m.group(1)) if total_m else sum(comps.values())
    return {"total": total, "components": comps}


def get_pj_per_hop() -> dict:
    """Run Accelergy once with a nominal 1-hop action count to get a
    calibrated pJ-per-hop coefficient. Raises RuntimeError with a clear
    message if Accelergy or the required input files aren't available —
    callers should treat that as "skip the NoC energy step", not a hard
    pipeline failure.

    Unlike a tempdir, ACCELERGY_OUT is committed to disk under results/ —
    action_counts.yaml, energy_estimation.yaml, ERT.yaml, ART.yaml, the
    flattened architecture, and accelergy's own stdout log all persist past
    this run. That's the audit trail for wherever "pJ_per_hop" ends up
    quoted (a paper, a dashboard, a teammate asking "where did 5.4 come
    from"): rerun `accelergy noc_arch.yaml noc_ERT.yaml action_counts.yaml`
    by hand inside results/accelergy/ and you get the identical files back.
    """
    if not NOC_ARCH.exists():
        raise RuntimeError(f"missing {NOC_ARCH}")
    ert_path = _find_noc_ert()
    if not ert_path:
        raise RuntimeError(f"missing noc_ERT.yaml in {TIMELOOP}")
    accelergy = os.environ.get("ACCELERGY_BIN") or "accelergy"

    ACCELERGY_OUT.mkdir(parents=True, exist_ok=True)
    # Clear stale outputs from a previous run first — if this run fails
    # partway through, we don't want last run's energy_estimation.yaml
    # sitting there looking like it belongs to today's run.
    for stale in ACCELERGY_OUT.glob("*.yaml"):
        stale.unlink()

    action_counts_path = ACCELERGY_OUT / "action_counts.yaml"
    _write_yaml(ONE_HOP_ACTION_COUNTS, action_counts_path)

    try:
        result = subprocess.run(
            [accelergy, str(NOC_ARCH.resolve()), str(ert_path.resolve()),
             str(action_counts_path.resolve())],
            cwd=ACCELERGY_OUT, capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"could not run '{accelergy}': {e}")

    (ACCELERGY_OUT / "accelergy_run.log").write_text(
        f"$ {accelergy} {NOC_ARCH} {ert_path} {action_counts_path}\n"
        f"(run at {datetime.now(timezone.utc).isoformat()}Z, "
        f"returncode={result.returncode})\n\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )

    est_path = ACCELERGY_OUT / "energy_estimation.yaml"
    if result.returncode != 0 or not est_path.exists():
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-15:])
        raise RuntimeError(
            f"accelergy failed (rc={result.returncode}) — see "
            f"{ACCELERGY_OUT / 'accelergy_run.log'} for the full log:\n{tail}"
        )
    return parse_energy_estimation(est_path.read_text())


CONFIGS_DIR = TRACK / "configs"


def _packet_size(topology: str) -> int:
    """Flits per packet for this topology's Booksim config. Every flit in a
    packet independently does its own buffer_write/buffer_read/crossbar/link
    sequence at each hop — a hop's *energy* cost scales with flits, not just
    with hop count. Defaults to 1 (single-flit packets) if the config is
    missing or has no packet_size line, which just means no scaling applies."""
    cfg = CONFIGS_DIR / f"{topology}.cfg"
    if not cfg.exists():
        return 1
    for line in cfg.read_text().splitlines():
        line = line.split("//")[0].strip()
        if line.startswith("packet_size"):
            try:
                return int(line.split("=")[1].strip().rstrip(";"))
            except (IndexError, ValueError):
                return 1
    return 1


def apply_to_sweep(sweep: list, pj_per_hop: float, packet_size_fn=_packet_size) -> dict:
    """topology -> sorted [(injection_rate, hops_avg, energy_pJ)] (valid points only).

    energy_pJ = hops_avg * packet_size * pj_per_hop — NOT hops_avg * pj_per_hop.
    hops_avg is hops per *packet*; each hop moves every flit in that packet
    through its own buffer_write + buffer_read + crossbar + link sequence, so
    the real event count per packet is hops_avg * flits_per_packet, not
    hops_avg alone. Skipping packet_size silently undercounts energy by
    exactly the packet's flit count for any packet_size > 1.

    packet_size_fn is injectable (defaults to the real configs/*.cfg lookup)
    so tests can pin known packet sizes instead of depending on whatever
    happens to be in configs/ on disk.
    """
    out = {}
    for r in sweep:
        hops = r.get("hops_avg")
        if hops is None:
            continue
        flits = packet_size_fn(r["topology"])
        out.setdefault(r["topology"], []).append(
            [r["injection_rate"], hops, round(hops * flits * pj_per_hop, 4)]
        )
    for t in out:
        out[t].sort()
    return out


def main():
    if not SWEEP.exists():
        sys.exit(f"  no {SWEEP} — run the Booksim sweep first (make ... CMD=timeloop / CMD=sim)")

    try:
        est = get_pj_per_hop()
    except RuntimeError as e:
        print(f"  NoC energy bridge skipped: {e}")
        print(f"  (this does not fail the sweep — {SWEEP} still has hops_avg)")
        return  # non-fatal: don't break `make timeloop` over a missing/misconfigured Accelergy step

    pj_per_hop = est["total"]
    sweep = json.loads(SWEEP.read_text())
    per_topology = apply_to_sweep(sweep, pj_per_hop)

    RESULTS.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "pj_per_hop": pj_per_hop,
        "components": est["components"],
        "per_topology": per_topology,
        "source": str((ACCELERGY_OUT / "energy_estimation.yaml").relative_to(TRACK)),
        "computed_at": datetime.now(timezone.utc).isoformat() + "Z",
    }, indent=2))

    print(f"  pJ/hop = {pj_per_hop}  ({', '.join(f'{k}={v}' for k, v in est['components'].items())})")
    for t, pts in per_topology.items():
        peak = max(p[2] for p in pts)
        print(f"    {t:<12} peak NoC energy proxy ≈ {peak} pJ (over {len(pts)} rate points)")
    print(f"  -> {OUT}")
    print(f"  -> {ACCELERGY_OUT}/ (accelergy inputs/outputs + accelergy_run.log — the audit trail for pJ/hop)")


def _selfcheck():
    sample_estimation = """energy_estimation:
    version: '0.4'
    components:
      - name: noc.router
        energy: 4.2
      - name: noc.link
        energy: 1.2
    Total: 5.4
"""
    est = parse_energy_estimation(sample_estimation)
    assert est["total"] == 5.4, est
    assert est["components"] == {"noc.router": 4.2, "noc.link": 1.2}, est

    sweep = [
        {"topology": "mesh4x4", "injection_rate": 0.1, "hops_avg": 2.0, "status": "ok"},
        {"topology": "mesh4x4", "injection_rate": 0.2, "hops_avg": 3.0, "status": "ok"},
        {"topology": "torus4x4", "injection_rate": 0.1, "hops_avg": 1.5, "status": "ok"},
        {"topology": "fly4", "injection_rate": 0.1, "hops_avg": None, "status": "no_output"},
    ]

    # packet_size=1 for every topology (pinned, not read from disk) — isolates
    # the base hops*pj_per_hop math from the packet_size multiplier below.
    per_topo = apply_to_sweep(sweep, est["total"], packet_size_fn=lambda t: 1)
    assert set(per_topo) == {"mesh4x4", "torus4x4"}, per_topo          # no-output rows excluded
    assert per_topo["mesh4x4"][0] == [0.1, 2.0, 10.8], per_topo         # 2.0 hops * 1 * 5.4 pJ/hop
    assert per_topo["mesh4x4"][1][0] == 0.2, per_topo                   # sorted by rate

    # packet_size=5 (your actual configs) must scale energy by exactly 5x,
    # NOT change hops_avg in the output — only the energy column moves.
    per_topo_5 = apply_to_sweep(sweep, est["total"], packet_size_fn=lambda t: 5)
    assert per_topo_5["mesh4x4"][0] == [0.1, 2.0, 54.0], per_topo_5     # 2.0 hops * 5 flits * 5.4 pJ/hop
    assert per_topo_5["mesh4x4"][0][1] == per_topo["mesh4x4"][0][1], "hops_avg must be unscaled"

    # _packet_size itself: parses "packet_size = 5;" out of a real cfg file,
    # ignores comments, defaults to 1 when the topology has no config at all.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "mesh4x4.cfg").write_text(
            "traffic = uniform;\n// packet_size = 999; (commented out, must be ignored)\npacket_size = 5;\n"
        )
        global CONFIGS_DIR
        saved, CONFIGS_DIR = CONFIGS_DIR, tmp
        try:
            assert _packet_size("mesh4x4") == 5, _packet_size("mesh4x4")
            assert _packet_size("nonexistent_topology") == 1
        finally:
            CONFIGS_DIR = saved

    print("selfcheck OK")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selfcheck":
        _selfcheck()
    else:
        main()