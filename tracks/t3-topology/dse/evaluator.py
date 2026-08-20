import os, re, subprocess, tempfile
from pathlib import Path
from .space import DesignPoint, SimResult

BOOKSIM_BIN = Path(os.environ.get(
    "BOOKSIM_BIN",
    str(Path(__file__).resolve().parent.parent.parent.parent /
        "third_party/booksim2/src/booksim"),
))


def _generate_cfg(point: DesignPoint, defaults: dict) -> str:
    v = {**defaults, **point.values}
    lines = [
        f"topology = {v.get('topology', 'mesh')};",
        f"k = {v.get('x_dim', 8)};",
        "n = 2;",
        f"num_vcs = {v.get('vcs', 4)};",
        f"vc_buf_size = {v.get('vc_buf', 8)};",
        f"routing_function = {v.get('routing', 'dor')};",
        f"traffic = {v.get('traffic', 'uniform')};",
        "sim_type = latency;",
        f"injection_rate = {v.get('injection_rate', 0.08)};",
        f"sample_period = {v.get('sample_period', 1000)};",
        "warmup_periods = 3;",
        f"max_samples = {v.get('max_samples', 10)};",
        f"latency_thres = {v.get('latency_thres', 5000)};",
        f"seed = {v.get('seed', 42)};",
    ]
    return "\n".join(lines) + "\n"


def run_booksim(point: DesignPoint, defaults: dict, timeout: int = 120) -> SimResult:
    if not BOOKSIM_BIN.exists():
        return SimResult(point, error=f"booksim binary not found: {BOOKSIM_BIN}")

    cfg_content = _generate_cfg(point, defaults)
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "dse.cfg"
        cfg_path.write_text(cfg_content)

        try:
            r = subprocess.run(
                [str(BOOKSIM_BIN), str(cfg_path)],
                capture_output=True, text=True, timeout=timeout, cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            return SimResult(point, error="timeout")
        except Exception as e:
            return SimResult(point, error=str(e))

        if r.returncode != 0:
            return SimResult(point, error=f"exit {r.returncode}: {r.stderr[:200]}")

        lat = hops = throughput = None
        for line in r.stdout.splitlines():
            m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", line)
            if m:
                lat = float(m.group(1))
            m = re.search(r"Hops average\s*=\s*([0-9.]+)", line)
            if m:
                hops = float(m.group(1))
            m = re.search(r"Throughput average\s*=\s*([0-9.]+)", line)
            if m:
                throughput = float(m.group(1))

        if lat is None:
            return SimResult(point, error=f"no latency in output: {r.stdout[-300:]}")

        return SimResult(point, avg_latency=lat, avg_hops=hops, throughput=throughput)
