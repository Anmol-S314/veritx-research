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
        elif key == "network_file":
            params["_network_file"] = val
        elif key == "total_nodes":
            try:
                params["total_nodes"] = int(val)
            except ValueError:
                pass

    # Explicit total_nodes in the cfg always wins (required for topologies
    # without a closed-form size). Never guess: a wrong count silently
    # simulates the wrong machine.
    if "total_nodes" in params:
        return params

    # Determine total node count
    if params["topology"] in ("mesh", "torus"):
        params["total_nodes"] = params["k"] ** params["n"]
    elif params["topology"] == "anynet":
        params["total_nodes"] = _count_anynet_nodes(cfg_path, params)
    elif params["topology"] in ("fly", "flatfly"):
        params["total_nodes"] = params["k"] ** params["n"]
    else:
        raise ValueError(
            f"cannot determine total_nodes for topology "
            f"'{params['topology']}': add an explicit 'total_nodes = N' "
            f"line to {cfg_path}")

    return params


def _count_anynet_nodes(cfg_path: Path, params: dict) -> int:
    """Count nodes from the anynet network file. Never guess."""
    net_file = params.get("_network_file", "")
    p = Path(net_file)
    if not p.is_absolute():
        p = cfg_path.parent / p
    if not net_file or not p.exists():
        raise FileNotFoundError(
            f"anynet topology needs 'network_file = <links file>' in "
            f"{cfg_path} (resolved to {p}); one '<src> <dst>' link per line.")
    nodes: set[int] = set()
    for line in p.read_text().splitlines():
        line = line.split("//")[0].split("#")[0].strip()
        toks = line.replace(",", " ").split()
        if len(toks) >= 2:
            try:
                nodes.add(int(toks[0]))
                nodes.add(int(toks[1]))
            except ValueError:
                pass
    if not nodes:
        raise ValueError(f"no '<src> <dst>' links found in anynet file {p}")
    return len(nodes)


def generate_astrasim_system_json(num_nodes: int, model_name: str = "Workload", allreduce_impl: str = "ring") -> dict:
    """Generate a standard ASTRA-Sim 2.0 system.json for N PU nodes."""
    return {
        "scheduling-policy": "LIFO",
        "endpoint-delay": 10,
        "active-chunks-per-dimension": 1,
        "preferred-dataset-splits": 1,
        "boost-mode": 0,
        # Collective names are case-sensitive lowercase (ring|oneRing|
        # doubleBinaryTree|direct*|oneDirect*|halvingDoubling|
        # oneHalvingDoubling per CollectiveImplLookup.cc); uppercase aborts.
        "all-reduce-implementation": [allreduce_impl],
        "all-gather-implementation": ["ring"],
        "reduce-scatter-implementation": ["ring"],
        "all-to-all-implementation": ["direct"],
        # Must be one of the Sys.cc-accepted values: baseline | localBWAware.
        # ("LocalBwd" is rejected at startup with a critical panic.)
        "collective-optimization": "localBWAware",
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


# Keys the astrasim adapter understands but BookSim's config parser does
# not — feeding them to the frontend aborts with "Parse error: Unknown
# integer field". They are stripped from the sanitized cfg copy.
_ADAPTER_ONLY_KEYS = {"total_nodes"}


def _write_sanitized_cfg(cfg_path: Path, out_dir: Path) -> Path:
    """Write a copy of the BookSim cfg with adapter-only keys stripped.

    The frontend re-parses the cfg through BookSim's own config parser,
    which rejects unknown fields — so the sanitized copy (not the original)
    is what network.json points at. It also documents the exact cfg each
    run consumed.
    """
    kept = []
    for line in cfg_path.read_text().splitlines():
        stripped = line.split("//")[0].split("#")[0].strip()
        if stripped and "=" in stripped:
            if stripped.split("=", 1)[0].strip() in _ADAPTER_ONLY_KEYS:
                continue
        kept.append(line)
    out = out_dir / cfg_path.name
    out.write_text("\n".join(kept) + "\n")
    return out


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
    net_json = generate_astrasim_network_json(
        _write_sanitized_cfg(cfg_path, out_dir), params)
    log_json = generate_astrasim_logical_topology_json(params["total_nodes"], tp=tp, pp=pp)
    # Remote-memory config: required flag for our frontend binaries (mirrors
    # serving's invocation, which passes memory_expansion.json for both memory
    # flags). num-nodes is set from the actual topology, not copied blindly.
    mem_json = {
        "memory-type": "PER_NODE_MEMORY_EXPANSION",
        "num-nodes": params["total_nodes"],
        "num-npus-per-node": 1,
        "remote-mem-latency": 100,
        "remote-mem-bw": 32768,
    }

    (out_dir / "system.json").write_text(json.dumps(sys_json, indent=2))
    (out_dir / "network.json").write_text(json.dumps(net_json, indent=2))
    (out_dir / "logical_topology.json").write_text(json.dumps(log_json, indent=2))
    (out_dir / "memory.json").write_text(json.dumps(mem_json, indent=2))

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
