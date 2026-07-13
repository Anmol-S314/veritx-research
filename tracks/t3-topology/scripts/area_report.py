#!/usr/bin/env python3
"""Real die area for the T3 accelerator, from Accelergy (T3 — Wk13 Pareto).

Why this is a separate step and not part of Timeloop:

  Timeloop *can* replace its internal area model with an Accelergy ART, but the
  pinned Timeloop (2022) hard-asserts on ERT `version: 0.3` and Accelergy 0.4
  emits `0.4` (and an empty ERT for this arch). Unpinning Timeloop drags in the
  barvinok/isl/NTL stack the Dockerfile deliberately avoids. So Timeloop keeps
  doing energy with its built-in PAT model, and Accelergy is queried directly
  for area -- which is strictly better anyway, because Timeloop's area model has
  no notion of the NoC, and the ROUTERS dominate the die.

Every number here comes from a real estimator. `dummy_tables` is removed from the
image on purpose: a component nobody can price makes Accelergy exit non-zero
rather than quietly inventing 1 pJ / 1 um^2.

  python3 scripts/area_report.py -n 16 -o results/area_16.json
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

TRACK = Path(__file__).parent.parent

sys.path.insert(0, str(Path(__file__).parent))
from run_experiments import nodes_from_cfg  # noqa: E402  (single source of node counts)


def topology_shape(cfg: Path):
    """(routers, radix) for a Booksim config, or None if the family isn't modelled.

    Router count and channel count come from Booksim's own network constructors,
    so radix is derived rather than assumed:

        radix = channels/routers  (inter-router ports)
              + nodes/routers     (injection/ejection, i.e. concentration)

    Verified against Booksim, which prints "# of channels = 32" for fattree16 --
    matching (2*k*k^(n-1))*(n-1) = 32 here.
    """
    txt = re.sub(r"//.*|#.*", "", cfg.read_text())

    def val(key):
        m = re.search(rf"\b{key}\s*=\s*([A-Za-z0-9_]+)\s*;", txt)
        return m.group(1) if m else None

    topo = val("topology")
    nodes = nodes_from_cfg(cfg)
    try:
        k, n = int(val("k")), int(val("n"))
    except (TypeError, ValueError):
        return None
    if not nodes:
        return None

    if topo in ("mesh", "torus", "cmesh"):        # kncube.cpp / cmesh.cpp
        routers = k ** n
        channels = 2 * n * routers
    elif topo == "fly":                            # fly.cpp
        routers = n * k ** (n - 1)
        channels = (n - 1) * nodes
    elif topo == "fattree":                        # fattree.cpp
        routers = n * k ** (n - 1)
        channels = (2 * k * k ** (n - 1)) * (n - 1)
    elif topo == "flatfly":                        # flatfly_onchip.cpp
        routers = k ** n
        c = int(val("c") or 1)
        channels = routers * (n * (k - 1))         # _r - _c = all-to-all per dim
    else:
        return None                                # dragonfly/anynet/qtree: not modelled

    if routers <= 0 or channels <= 0:
        return None
    # Booksim builds uniform routers, so this is the per-router port count. For
    # fattree it is an average -- its levels genuinely differ in degree.
    radix = channels / routers + nodes / routers
    return routers, radix

# Each backend supports only certain nodes, and they do not overlap:
#   Aladdin (regfile, intmac)   -> 40/45nm only
#   Library (isaac_router)      -> 32nm only
#   CACTI  (SRAM/DRAM)          -> 22-180nm, interpolated
# So a single consistent node is impossible with the shipped backends. Rather
# than silently mix them, every component carries the node it was priced at.
TECH = {"regfile": 45, "intmac": 45, "SRAM": 45, "crossbar": 45}


def accelergy_arch(rf_entries, gb_kb, word_bits, routers=None, flit_bits=128,
                   vc_buf_entries=32):
    """One entry per component *type*; instance counts are applied afterwards.

    `routers` is {label: radix}. A router is built from primitives rather than
    taken as a fixed block, so its area actually responds to topology:

        crossbar     O(radix^2) -- the dominant term
        input buffer O(radix)   -- one per port, num_vcs * vc_buf_size flits deep

    The shipped isaac_router is a flat 150000 um^2 at any radix, which prices a
    5-port mesh router identically to a 10-port flatfly router. That makes a
    topology-vs-area comparison meaningless, which is the whole point of T3.
    """
    gb_width = 64  # bits per row; CACTI needs width >= 32
    gb_depth = max(64, (gb_kb * 1024 * 8) // gb_width)
    local = [
        {"name": "RegisterFile", "class": "regfile",
         "attributes": {"technology": TECH["regfile"],
                        "width": word_bits, "depth": rf_entries}},
        {"name": "GlobalBuffer", "class": "SRAM",
         "attributes": {"technology": TECH["SRAM"],
                        "width": gb_width, "depth": gb_depth}},
        {"name": "MAC", "class": "intmac",
         "attributes": {"technology": TECH["intmac"], "width": word_bits}},
    ]
    for label, radix in (routers or {}).items():
        r = max(2, int(round(radix)))
        local += [
            {"name": f"Crossbar_{label}", "class": "crossbar",
             "attributes": {"technology": TECH["crossbar"],
                            "n_inputs": r, "n_outputs": r, "width": flit_bits}},
            # One input buffer per port. Depth is num_vcs * vc_buf_size (both read
            # from the .cfg); CACTI needs depth >= 64, and a real NoC buffer is
            # deeper than that anyway.
            {"name": f"InBuf_{label}", "class": "regfile",
             "attributes": {"technology": TECH["regfile"],
                            "width": flit_bits,
                            "depth": max(64, vc_buf_entries)}},
        ]
    return {"architecture": {"version": 0.3,
                             "subtree": [{"name": "system", "local": local}]}}


def run_accelergy(arch: dict):
    """-> {component: area_um2_per_instance}. Raises if a component can't be priced."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "arch.yaml").write_text(yaml.safe_dump(arch, sort_keys=False))
        proc = subprocess.run(["accelergy", "arch.yaml", "-o", ".", "--oprefix", ""],
                              cwd=d, capture_output=True, text=True, timeout=600)
        art = d / "ART.yaml"
        if not art.exists():
            err = [l for l in (proc.stdout + proc.stderr).splitlines()
                   if re.search(r"ERROR|Can not find", l)]
            raise SystemExit("✗ Accelergy could not price the architecture:\n  "
                             + "\n  ".join(err[:4] or ["(see accelergy output)"]))
        tables = yaml.safe_load(art.read_text())["ART"]["tables"]
        return {t["name"].split(".")[-1]: float(t["area"]) for t in tables}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--nodes", type=int,
                    help="NoC node count == PE count == router count")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--flit-bits", type=int, default=128,
                    help="NoC channel width in bits (Booksim counts flits, not bits)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        return _selfcheck()
    if not args.nodes:
        ap.error("-n/--nodes is required")

    arch = yaml.safe_load((TRACK / "timeloop" / "arch.yaml").read_text())["arch"]
    word_bits = arch["arithmetic"].get("word-bits", 8)
    store = {l["name"]: l for l in arch["storage"]}
    rf_entries = store["RegisterFile"]["entries"]
    gb_kb = store["GlobalBuffer"]["sizeKB"]

    # Every topology at this node count, with its own radix.
    shapes, skipped = {}, []
    for cfg in sorted((TRACK / "configs").glob("*.cfg")):
        if nodes_from_cfg(cfg) != args.nodes:
            continue
        shape = topology_shape(cfg)
        if shape:
            shapes[cfg.stem] = shape
        else:
            skipped.append(cfg.stem)
    if not shapes:
        sys.exit(f"✗ no configs/*.cfg with {args.nodes} nodes.")

    vc_entries = _vc_buffer_entries(next(iter(
        c for c in (TRACK / "configs").glob("*.cfg") if c.stem in shapes)))

    per_inst = run_accelergy(accelergy_arch(
        rf_entries, gb_kb, word_bits,
        routers={t: radix for t, (_, radix) in shapes.items()},
        flit_bits=args.flit_bits, vc_buf_entries=vc_entries))

    # Shared across every topology of this size: the PE array and the buffer.
    base = {
        "RegisterFile": {"instances": args.nodes, "each": per_inst["RegisterFile"],
                         "tech": TECH["regfile"]},
        "MAC": {"instances": args.nodes, "each": per_inst["MAC"], "tech": TECH["intmac"]},
        "GlobalBuffer": {"instances": 1, "each": per_inst["GlobalBuffer"],
                         "tech": TECH["SRAM"]},
    }
    for c in base.values():
        c["total"] = round(c["each"] * c["instances"], 2)
        c["each"] = round(c["each"], 2)
    base_total = sum(c["total"] for c in base.values())

    topos = {}
    for t, (routers, radix) in sorted(shapes.items()):
        xbar = per_inst[f"Crossbar_{t}"]
        buf = per_inst[f"InBuf_{t}"] * max(2, int(round(radix)))  # one per port
        each = xbar + buf
        total_routers = each * routers
        topos[t] = {
            "routers": routers,
            "radix": round(radix, 2),
            "crossbar_um2_each": round(xbar, 2),
            "buffers_um2_each": round(buf, 2),
            "router_um2_each": round(each, 2),
            "noc_um2_total": round(total_routers, 2),
            "total_area_um2": round(base_total + total_routers, 2),
            "total_area_mm2": round((base_total + total_routers) / 1e6, 4),
            "noc_share_pct": round(total_routers / (base_total + total_routers) * 100, 1),
        }

    out = {
        "nodes": args.nodes,
        "rf_entries": rf_entries,
        "global_buffer_kB": gb_kb,
        "flit_bits": args.flit_bits,
        "vc_buffer_entries": vc_entries,
        "base_um2": round(base_total, 2),   # PE array + buffer; same for all topologies
        "base_components": base,
        "topologies": topos,
    }
    dest = Path(args.out or TRACK / "results" / f"area_{args.nodes}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))

    print(f"  {args.nodes}-node die area — routers priced by radix "
          f"({args.flit_bits}b flits, {vc_entries}-flit buffers)")
    print(f"    PE array + GlobalBuffer (same for every topology): "
          f"{base_total:,.0f} um^2")
    print()
    print(f"    {'topology':<12} {'radix':>6} {'rtrs':>5} {'router ea':>11} "
          f"{'NoC total':>12} {'die mm^2':>9} {'NoC %':>6}")
    for t, d in sorted(topos.items(), key=lambda kv: kv[1]["total_area_um2"]):
        print(f"    {t:<12} {d['radix']:>6} {d['routers']:>5} "
              f"{d['router_um2_each']:>11,.0f} {d['noc_um2_total']:>12,.0f} "
              f"{d['total_area_mm2']:>9} {d['noc_share_pct']:>5}%")
    if skipped:
        print(f"    (no radix model for: {', '.join(skipped)} — not priced)")
    print(f"  -> {dest}")


def _vc_buffer_entries(cfg: Path):
    """num_vcs * vc_buf_size — the flits an input port must hold."""
    txt = re.sub(r"//.*|#.*", "", cfg.read_text())

    def val(key, default):
        m = re.search(rf"\b{key}\s*=\s*(\d+)\s*;", txt)
        return int(m.group(1)) if m else default

    return val("num_vcs", 4) * val("vc_buf_size", 8)


def _selfcheck():
    import tempfile as tf
    d = Path(tf.mkdtemp())

    def cfg(name, body):
        (d / name).write_text(body)
        return d / name

    # radix = channels/routers + nodes/routers, from Booksim's own constructors.
    mesh = cfg("m.cfg", "topology = mesh; k = 4; n = 2;\nnum_vcs = 4;\nvc_buf_size = 8;\n")
    assert topology_shape(mesh) == (16, 5.0), topology_shape(mesh)   # 4 neighbours + local
    tor = cfg("t.cfg", "topology = torus; k = 4; n = 2;\n")
    assert topology_shape(tor) == (16, 5.0)                          # wraparound: same radix
    cm = cfg("c.cfg", "topology = cmesh; k = 2; n = 2; c = 4;\n")
    assert topology_shape(cm) == (4, 8.0), topology_shape(cm)        # 4 mesh + 4 concentrated
    ft = cfg("f.cfg", "topology = fattree; k = 4; n = 2;\n")
    # channels = (2*4*4)*1 = 32 -- Booksim itself prints "# of channels = 32"
    assert topology_shape(ft) == (8, 6.0), topology_shape(ft)
    ff = cfg("ff.cfg", "topology = flatfly; k = 4; n = 2; c = 4;\n")
    assert topology_shape(ff) == (16, 10.0), topology_shape(ff)      # 2*(4-1) + 4
    assert topology_shape(cfg("d.cfg", "topology = dragonflynew; k = 4; n = 1;\n")) is None

    # a bigger mesh has MORE routers but the SAME radix -- area must scale with
    # count, not degree, or the topology comparison is measuring the wrong thing
    big = cfg("m8.cfg", "topology = mesh; k = 8; n = 2;\n")
    assert topology_shape(big) == (64, 5.0), topology_shape(big)

    assert _vc_buffer_entries(mesh) == 32                            # 4 vcs x 8 flits
    a = accelergy_arch(64, 32, 8, routers={"mesh": 5, "flatfly": 10})
    names = {c["name"] for c in a["architecture"]["subtree"][0]["local"]}
    assert {"Crossbar_mesh", "InBuf_mesh", "Crossbar_flatfly"} <= names, names
    xb = {c["name"]: c for c in a["architecture"]["subtree"][0]["local"]}
    assert xb["Crossbar_flatfly"]["attributes"]["n_inputs"] == 10     # radix drives the crossbar
    assert xb["Crossbar_mesh"]["attributes"]["n_inputs"] == 5
    print("selfcheck OK")


if __name__ == "__main__":
    main()
