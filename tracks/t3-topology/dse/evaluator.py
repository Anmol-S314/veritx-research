import os, re, subprocess, shutil, tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from space import DesignPoint, SimResult

BOOKSIM_BIN = Path(os.environ.get(
    "BOOKSIM_BIN",
    str(Path(__file__).resolve().parent.parent.parent.parent /
        "third_party/booksim2/src/booksim"),
))
# Scratch dir for BookSim2 outputs — repo disk, never /tmp (tmpfs/RAM-backed)
SCRATCH = Path(os.environ.get(
    "DSE_SCRATCH",
    str(Path(__file__).resolve().parent / ".scratch"),
))


def _generate_cfg(point: DesignPoint, defaults: dict, workdir: Path) -> str:
    v = {**defaults, **point.values}
    traffic = v.get('traffic', 'uniform')
    # Real traffic: 'traffic = matrix(<file>)' with the matrix copied into the
    # workdir so BookSim2 resolves it relative to the cfg.
    tf = v.get('traffic_file')
    if tf is not None:
        dst = workdir / "traffic.matrix"
        shutil.copyfile(tf, dst)
        traffic = f"matrix({dst.name})"
    lines = [
        f"topology = {v.get('topology', 'mesh')};",
        f"k = {v.get('x_dim', 8)};",
        "n = 2;",
        f"num_vcs = {v.get('vcs', 4)};",
        f"vc_buf_size = {v.get('vc_buf', 8)};",
        f"routing_function = {v.get('routing', 'dor')};",
        f"traffic = {traffic};",
        "sim_type = latency;",
        f"injection_rate = {v.get('injection_rate', 0.08)};",
        f"seed = {v.get('seed', 42)};",
    ]
    return "\n".join(lines) + "\n"


def run_booksim(point: DesignPoint, defaults: dict, timeout: int = 120) -> SimResult:
    if not BOOKSIM_BIN.exists():
        return SimResult(point, error=f"booksim binary not found: {BOOKSIM_BIN}")

    SCRATCH.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(dir=SCRATCH))
    try:
        cfg_content = _generate_cfg(point, defaults, workdir)
        cfg_path = workdir / "dse.cfg"
        cfg_path.write_text(cfg_content)

        try:
            r = subprocess.run(
                [str(BOOKSIM_BIN), str(cfg_path)],
                capture_output=True, text=True, timeout=timeout, cwd=workdir,
            )
        except subprocess.TimeoutExpired:
            return SimResult(point, error="timeout")
        except Exception as e:
            return SimResult(point, error=str(e))

        lat = hops = throughput = None
        for line in r.stdout.splitlines():
            m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", line)
            if m:
                lat = float(m.group(1))
            m = re.search(r"Hops average\s*=\s*([0-9.]+)", line)
            if m:
                hops = float(m.group(1))
            m = re.search(r"Accepted packet rate average\s*=\s*([0-9.]+)", line)
            if m:
                throughput = float(m.group(1))

        if lat is None:
            return SimResult(
                point,
                error=f"exit {r.returncode}: no latency in output: {r.stdout[-300:]}",
            )

        return SimResult(point, avg_latency=lat, avg_hops=hops, throughput=throughput)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
