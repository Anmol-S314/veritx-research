#!/usr/bin/env python3
"""ASTRA-Sim 2.0 Adapter for T3 BookSim topologies.

Translates BookSim configuration files (configs/*.cfg) and T3 track parameters
into ASTRA-Sim 2.0 compatible JSON configuration files:
  - system.json             (compute & memory timing parameters)
  - network.json            (BookSim 2.0 backend binding)
  - logical_topology.json   (collective communication ring/tree dimensions)

Usage
-----
    python3 scripts/astrasim_adapter.py --cfg configs/mesh4x4.cfg --out-dir /tmp/astrasim_config
    python3 scripts/astrasim_adapter.py --selfcheck
"""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
TRACK = HERE.parent
CONFIGS_DIR = TRACK / "configs"


def parse_booksim_cfg(cfg_path: Path) -> dict:
    """Extract key topology parameters from a BookSim .cfg file."""
    if not cfg_path.exists():
        raise FileNotFoundError(f"BookSim config not found: {cfg_path}")

    params = {
        "topology": "mesh",
        "k": 4,
        "n": 2,
        "num_vcs": 4,
        "vc_buf_size": 4,
        "packet_size": 1,
        "routing_function": "min",
        "subnets": 1,
    }

    for line in cfg_path.read_text().splitlines():
        line = line.split("//")[0].split("#")[0].strip()
        if not line or "=" not in line:
            continue
        key, val = [x.strip().rstrip(";") for x in line.split("=", 1)]

        if key == "topology":
            params["topology"] = val
        elif key in ("k", "n", "num_vcs", "vc_buf_size", "packet_size", "subnets"):
            try:
                params[key] = int(val)
            except ValueError:
                pass
        elif key == "routing_function":
            params["routing_function"] = val

    # Determine total node count
    if params["topology"] in ("mesh", "torus"):
        params["total_nodes"] = params["k"] ** params["n"]
    elif params["topology"] == "anynet":
        params["total_nodes"] = 16
    elif params["topology"] in ("fly", "flatfly"):
        params["total_nodes"] = params["k"] ** params["n"]
    else:
        params["total_nodes"] = 16

    return params


def generate_astrasim_system_json(num_nodes: int, model_name: str = "Workload", allreduce_impl: str = "RING") -> dict:
    """Generate a standard ASTRA-Sim 2.0 system.json for N PU nodes."""
    return {
        "scheduling-policy": "LIFO",
        "endpoint-delay": 10,
        "active-chunks-per-dimension": 1,
        "preferred-dataset-splits": 1,
        "boost-mode": 0,
        "all-reduce-implementation": [allreduce_impl],
        "all-gather-implementation": ["RING"],
        "reduce-scatter-implementation": ["RING"],
        "all-to-all-implementation": ["DIRECT"],
        "collective-optimization": "LocalBwd",
        "system-name": f"T3_NOC_{num_nodes}Node_{model_name}",
    }


def generate_astrasim_network_json(cfg_path: Path, params: dict) -> dict:
    """Generate ASTRA-Sim 2.0 network.json specifying BookSim 2.0 backend."""
    return {
        "topology-type": "Booksim",
        "booksim-config-file": str(cfg_path.resolve()),
        "num-nodes": params["total_nodes"],
        "npus-per-node": 1,
        "bandwidth": 100.0,  # GB/s link bandwidth
        "latency": 10,       # ns link latency
    }


def generate_astrasim_logical_topology_json(num_nodes: int, tp: int = 1, pp: int = 1) -> dict:
    """Generate logical topology breakdown for collective operations and parallelism."""
    if tp > 1 and pp > 1 and (tp * pp == num_nodes):
        dims = [tp, pp]
    else:
        dims = [num_nodes]
    return {
        "logical-dimensions": dims
    }


def prepare_astrasim_config_dir(cfg_path: Path, out_dir: Path, spec: dict | None = None) -> dict:
    """Write system.json, network.json, logical_topology.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    params = parse_booksim_cfg(cfg_path)

    model_name = spec.get("model_name", "Workload") if spec else "Workload"
    tp = spec.get("tp_degree", 1) if spec else 1
    pp = spec.get("pp_degree", 1) if spec else 1

    sys_json = generate_astrasim_system_json(params["total_nodes"], model_name=model_name)
    net_json = generate_astrasim_network_json(cfg_path, params)
    log_json = generate_astrasim_logical_topology_json(params["total_nodes"], tp=tp, pp=pp)

    (out_dir / "system.json").write_text(json.dumps(sys_json, indent=2))
    (out_dir / "network.json").write_text(json.dumps(net_json, indent=2))
    (out_dir / "logical_topology.json").write_text(json.dumps(log_json, indent=2))

    return {
        "out_dir": str(out_dir),
        "topology": params["topology"],
        "total_nodes": params["total_nodes"],
    }


def _selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        cfg = tp / "mesh4x4.cfg"
        cfg.write_text("topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n")

        res = prepare_astrasim_config_dir(cfg, tp / "astrasim_out")
        assert (tp / "astrasim_out" / "system.json").exists()
        assert (tp / "astrasim_out" / "network.json").exists()
        assert (tp / "astrasim_out" / "logical_topology.json").exists()

        net_data = json.loads((tp / "astrasim_out" / "network.json").read_text())
        assert net_data["topology-type"] == "Booksim"
        assert net_data["num-nodes"] == 16

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cfg", default=str(CONFIGS_DIR / "mesh4x4.cfg"),
                    help="path to BookSim config file")
    ap.add_argument("--out-dir", default=None,
                    help="output directory for ASTRA-Sim JSON files")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    cfg = Path(args.cfg)
    out_dir = Path(args.out_dir) if args.out_dir else TRACK / "results" / "astrasim_configs" / cfg.stem
    res = prepare_astrasim_config_dir(cfg, out_dir)
    print(f"  ✓ Generated ASTRA-Sim configs for {res['topology']} ({res['total_nodes']} nodes) → {res['out_dir']}")


if __name__ == "__main__":
    main()
