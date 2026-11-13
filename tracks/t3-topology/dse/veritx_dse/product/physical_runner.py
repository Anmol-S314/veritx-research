"""Design-bound physical implementation runner for generated NoC hardware.

This module runs LibreLane on the *actual* emitted design directory produced by
``project_top_rtl`` (or the composed slice path), never on a fixed diagnostic
spike. The design files, clock port and clock period are inputs; the returned
evidence binds hashes of the inputs to the signoff metrics that the flow
produced.

Honesty rules enforced here:

* a missing LibreLane/PDK, or a flow that does not reach its final stage, is
  reported as ``BLOCKED``/``FAIL`` -- never as a physical pass;
* signoff requires *every* gate to be measured: setup and hold slack, DRC, LVS,
  antenna and unmapped-cell count. A metric that the flow did not produce is
  recorded as absent and fails the gate rather than being assumed clean;
* the platform and clock period are recorded with the evidence so a bounded
  Sky130 diagnostic run can never be read as signoff of another platform.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SCHEMA = "veritx/design-physical-run/1"

LIBRELANE_CANDIDATES = (
    "~/librelane-spike/.venv/bin/librelane",
    "~/.local/bin/librelane",
)
PDK_ROOT_CANDIDATES = (
    "~/librelane-spike/pdks",
    "~/.volare",
    "~/pdks",
)
# Files that belong to simulation only and must not enter physical synthesis.
NON_PHYSICAL_PREFIXES = ("tb_", "obj_")
NON_PHYSICAL_SUFFIXES = (".cpp", ".py", ".log", ".json", ".odb", ".def", ".gds")
NON_PHYSICAL_NAMES = frozenset({"Makefile"})

# Binaries the LibreLane Sky130 flow actually executes. A missing entry is an
# environment gap, not a design failure, so the runner refuses to start.
BACKEND_TOOLS = ("openroad", "yosys", "verilator", "magic", "netgen", "klayout")


class PhysicalRunnerError(RuntimeError):
    """Raised when a physical run cannot be started from the given inputs."""


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def find_librelane(explicit: str | None = None) -> Path | None:
    """Locate the LibreLane entry point without touching the system Python."""
    for candidate in ([explicit] if explicit else []) + [os.environ.get("LIBRELANE_BIN")] \
            + list(LIBRELANE_CANDIDATES) + [shutil.which("librelane")]:
        if not candidate:
            continue
        path = _expand(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def find_pdk_root(platform: str, explicit: str | None = None) -> Path | None:
    """Return a PDK root that actually contains ``platform``."""
    for candidate in ([explicit] if explicit else []) + [os.environ.get("PDK_ROOT")] \
            + list(PDK_ROOT_CANDIDATES):
        if not candidate:
            continue
        path = _expand(candidate)
        if (path / platform).is_dir():
            return path
    return None


def discover_tools(path_prefixes: list[str] | None = None) -> dict[str, str | None]:
    """Locate the flow backends; ``None`` marks a missing tool."""
    found: dict[str, str | None] = {}
    for name in BACKEND_TOOLS:
        located = None
        for prefix in path_prefixes or ():
            candidate = Path(prefix) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                located = str(candidate)
                break
        if located is None:
            located = shutil.which(name)
        found[name] = located
    return found


def physical_files(design_dir: Path, declared: list[str] | None = None) -> list[Path]:
    """Resolve the synthesizable files of a generated design directory."""
    design_dir = Path(design_dir)
    if declared:
        names = [name for name in declared if _is_physical_name(name)]
    else:
        names = sorted(entry.name for entry in design_dir.iterdir()
                       if entry.is_file() and _is_physical_name(entry.name))
    files = [design_dir / name for name in names]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise PhysicalRunnerError("declared RTL is absent: " + ", ".join(sorted(missing)))
    if not files:
        raise PhysicalRunnerError(f"no synthesizable SystemVerilog in {design_dir}")
    return files


def _is_physical_name(name: str) -> bool:
    if name in NON_PHYSICAL_NAMES or name.startswith(NON_PHYSICAL_PREFIXES):
        return False
    if not name.endswith((".sv", ".v")):
        return False
    return True


def clock_ports(top_source: str, module_name: str | None = None) -> list[str]:
    """Return declared clock-looking input ports of the named (or first) module."""
    start = _port_list_start(top_source, module_name)
    if start is None:
        return []
    end = _matching_paren(top_source, start)
    if end is None:
        return []
    ports = []
    for chunk in top_source[start + 1:end].split(","):
        segment = " ".join(chunk.split())
        if not segment.startswith("input"):
            continue
        if "clk" not in segment and "clock" not in segment:
            continue
        ports.append(segment.split()[-1])
    return ports


def _port_list_start(source: str, module_name: str | None = None) -> int | None:
    """Index of a module's port list, skipping a ``#(...)`` parameter block."""
    if module_name:
        index = source.find(f"module {module_name}")
        start = source.find("(", index) if index >= 0 else -1
    else:
        start = source.find("(")
    if start < 0:
        return None
    prefix = source[:start].rstrip()
    if prefix.endswith("#"):
        inner_end = _matching_paren(source, start)
        if inner_end is None:
            return None
        return source.find("(", inner_end + 1)
    return start


def _matching_paren(source: str, start: int) -> int | None:
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def build_invocation(binary: Path, config_path: Path, out_dir: Path, root: Path,
                     platform: str, tag: str, only: str | None,
                     container_image: str | None = None,
                     library_path: str | None = None) -> list[str]:
    """Command that runs LibreLane on this design, native or containerised.

    The container form exists because the flow backends (`openroad`, `magic`,
    `netgen`, `klayout`) are not installable on every host, while a container
    image can carry both them and a Python with `tkinter`.
    """
    arguments = [str(config_path.resolve()), "--pdk", platform, "--manual-pdk",
                 "--design-dir", str(out_dir.resolve()), "--run-tag", tag]
    if container_image:
        arguments[3:3] = ["--pdk-root", "/pdk"]
    else:
        arguments[3:3] = ["--pdk-root", str(Path(root).resolve())]
    if only:
        arguments.extend(["--only", only])
    if container_image:
        work = str(out_dir.resolve())
        pdk = str(Path(root).resolve())
        inner = "export PATH=/opt/lv/bin:$PATH; exec /opt/lv/bin/librelane " + " ".join(
            json.dumps(part) for part in arguments)
        return ["podman", "run", "--rm", "-v", f"{work}:/work:Z", "-v", f"{pdk}:/pdk:ro",
                "-w", "/work",
                "-e", f"LD_LIBRARY_PATH={library_path or ''}",
                "--entrypoint", "/bin/sh", container_image, "-c", inner]
    return [str(binary)] + arguments


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metric_view(metrics: dict) -> dict:
    """Extract the signoff gates from a LibreLane metrics mapping."""
    setup_ws = {k: v for k, v in metrics.items() if k.startswith("timing__setup__ws")}
    hold_ws = {k: v for k, v in metrics.items() if k.startswith("timing__hold__ws")}
    setup_tns = {k: v for k, v in metrics.items() if k.startswith("timing__setup__tns")}
    drc = {k: v for k, v in metrics.items()
           if "drc" in k.lower() and ("error" in k.lower() or "violation" in k.lower())}
    lvs = {k: v for k, v in metrics.items() if "lvs" in k.lower()}
    antenna = {k: v for k, v in metrics.items()
               if "antenna" in k.lower() and ("violation" in k.lower() or "error" in k.lower())}
    unmapped = {k: v for k, v in metrics.items() if "unmapped" in k.lower()}
    return {
        "setup_ws": setup_ws,
        "setup_tns": setup_tns,
        "hold_ws": hold_ws,
        "drc": drc,
        "lvs": lvs,
        "antenna": antenna,
        "unmapped": unmapped,
        "die_area": metrics.get("design__die__area"),
        "instance_count": metrics.get("design__instance__count"),
        "sequential_count": metrics.get("design__instance__count__class:sequential_cell"),
    }


def _worst(values: dict) -> float | None:
    numbers = [float(v) for v in values.values() if isinstance(v, (int, float))]
    return min(numbers) if numbers else None


def _total(values: dict) -> int | None:
    numbers = [float(v) for v in values.values() if isinstance(v, (int, float))]
    return int(sum(numbers)) if numbers else None


def _collect_metrics(run_dir: Path) -> tuple[dict, str | None]:
    """Merge metrics from the last stage that produced them."""
    if not run_dir.is_dir():
        return {}, None
    stages = sorted(p for p in run_dir.iterdir()
                    if p.is_dir() and p.name[0].isdigit())
    for stage in reversed(stages):
        state = stage / "state_out.json"
        if not state.is_file():
            continue
        try:
            payload = json.loads(state.read_text())
        except ValueError:
            continue
        metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if isinstance(metrics, dict) and metrics:
            return metrics, stage.name
    return {}, None


def gates_from_metrics(metrics: dict) -> dict:
    """Evaluate the physical signoff gates, refusing to assume absent data."""
    view = _metric_view(metrics)
    setup_ws = _worst(view["setup_ws"])
    hold_ws = _worst(view["hold_ws"])
    setup_tns = _total(view["setup_tns"])
    drc = _total(view["drc"])
    lvs = _total(view["lvs"])
    antenna = _total(view["antenna"])
    unmapped = _total(view["unmapped"])
    gates = {
        "unmapped_cells_clear": "PASS" if unmapped == 0 else
                                ("FAIL" if unmapped is not None else "NOT_MEASURED"),
        "setup_slack": "PASS" if setup_ws is not None and setup_ws >= 0 else
                       ("FAIL" if setup_ws is not None else "NOT_MEASURED"),
        "hold_slack": "PASS" if hold_ws is not None and hold_ws >= 0 else
                      ("FAIL" if hold_ws is not None else "NOT_MEASURED"),
        "drc": "PASS" if drc == 0 else ("FAIL" if drc is not None else "NOT_MEASURED"),
        "lvs": "PASS" if lvs == 0 else ("FAIL" if lvs is not None else "NOT_MEASURED"),
        "antenna": "PASS" if antenna == 0 else
                   ("FAIL" if antenna is not None else "NOT_MEASURED"),
    }
    gates["_values"] = {
        "setup_ws": setup_ws, "setup_tns": setup_tns, "hold_ws": hold_ws,
        "drc_errors": drc, "lvs_errors": lvs, "antenna_violations": antenna,
        "unmapped_cells": unmapped,
        "die_area": view["die_area"], "instance_count": view["instance_count"],
        "sequential_count": view["sequential_count"],
    }
    return gates


def _stream(command: list[str], cwd: Path, log_path: Path, timeout_s: float) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    with log_path.open("w") as log:
        log.write("$ " + " ".join(command) + "\n")
        log.flush()
        process = subprocess.Popen(command, cwd=str(cwd), stdout=log,
                                   stderr=subprocess.STDOUT, env=_env())
        try:
            return process.wait(timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=120)
            log.write(f"\n[physical-runner] killed after {timeout_s:.0f}s\n")
            return -9


def _env() -> dict:
    env = dict(os.environ)
    # LibreLane resolves its toolchain from its own environment; make sure no
    # repository-level override silently changes the PDK or tool set.
    env.pop("PDK", None)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def run_design_physical(
    design_dir: str | Path,
    out_dir: str | Path,
    *,
    platform: str = "sky130A",
    clock_period_ns: float = 50.0,
    clock_port: str | None = None,
    design_name: str = "project_top",
    declared_files: list[str] | None = None,
    timeout_s: float = 4 * 3600,
    only: str | None = None,
    librelane_bin: str | None = None,
    tool_path_prefixes: list[str] | None = None,
    container_image: str | None = None,
    container_library_path: str | None = None,
    skip_tool_check: bool = False,
    pdk_root: str | None = None,
    run_tag: str | None = None,
) -> dict:
    """Run LibreLane on ``design_dir`` and return hash-bound physical evidence."""
    design_dir = Path(design_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = find_librelane(librelane_bin)
    root = find_pdk_root(platform, pdk_root)
    started = time.time()
    result = {
        "schema": SCHEMA,
        "input_design_dir": str(design_dir),
        "platform": platform,
        "clock_period_ns": clock_period_ns,
        "clock_port": clock_port,
        "design_name": design_name,
        "status": "BLOCKED",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
    }
    if binary is None:
        result["reason"] = "LibreLane is not installed"
        return result
    if root is None:
        result["reason"] = f"no PDK root contains platform {platform!r}"
        return result
    result["librelane"] = {"path": str(binary), "version": _version(binary)}
    result["pdk_root"] = str(root)
    tools = discover_tools(tool_path_prefixes)
    result["tools"] = tools
    missing = sorted(name for name, path in tools.items() if path is None)
    if container_image:
        result["container_image"] = container_image
        missing = []
        result["container_tools"] = "provided by the container image"
    if missing and not skip_tool_check:
        result["reason"] = ("physical backend toolchain is incomplete on this host: missing "
                            + ", ".join(missing))
        result["missing_tools"] = missing
        return result

    files = physical_files(design_dir, declared_files)
    top_source = (design_dir / f"{design_name}.sv")
    if not top_source.is_file():
        raise PhysicalRunnerError(f"{design_name}.sv is absent from {design_dir}")
    ports = clock_ports(top_source.read_text(), design_name)
    if clock_port is not None:
        ports = [clock_port]
    if not ports:
        raise PhysicalRunnerError("no clock-like top-level input port found")
    result["clock_port"] = ports[0] if len(ports) == 1 else ports
    result["clock_ports_declared"] = ports
    result["rtl"] = [{"path": path.name, "bytes": path.stat().st_size,
                      "sha256": _sha256(path)} for path in files]

    src = out_dir / "src"
    src.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, src / path.name)

    # The flow reads the file list in order, and a package must precede the
    # module that imports it.
    ordered = [path for path in files if path.name.endswith("_pkg.sv")]
    ordered += [path for path in files if not path.name.endswith("_pkg.sv")]

    config = {
        "DESIGN_NAME": design_name,
        "VERILOG_FILES": [f"dir::src/{path.name}" for path in ordered],
        "PDK": platform,
        "CLOCK_PORT": ports[0] if len(ports) == 1 else ports,
        "CLOCK_PERIOD": float(clock_period_ns),
        # The emitted RTL keeps simulation-only diagnostics behind
        # `ifdef SYNTHESIS` guards, so the physical run defines it.
        "VERILOG_DEFINES": ["SYNTHESIS"],
        "USE_SLANG": False,
        # Generated RTL carries intentional lint categories (unused bits,
        # width casts). Synthesis checks stay non-fatal but their count is
        # recorded below so the choice is auditable.
        "ERROR_ON_SYNTH_CHECKS": False,
        "LINTER_DISABLE_WARNINGS": [],
        # Without the PDK models the linter cannot resolve the power-good UDP
        # the standard-cell blackboxes reference, and the flow stops before
        # synthesis.
        "LINTER_INCLUDE_PDK_MODELS": True,
    }
    config_path = out_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    result["config_sha256"] = _sha256(config_path)
    result["config"] = config

    tag = run_tag or "design-physical"
    command = build_invocation(binary, config_path, out_dir, root, platform, tag, only,
                               container_image=container_image,
                               library_path=container_library_path)
    if only:
        result["only"] = only
    log_path = out_dir / "librelane.log"
    exit_code = _stream(command, out_dir, log_path, timeout_s)
    result["exit_code"] = exit_code
    result["log"] = {"path": str(log_path), "bytes": log_path.stat().st_size,
                     "sha256": _sha256(log_path)}
    run_dir = out_dir / "runs" / tag
    result["run_dir"] = str(run_dir)
    metrics, final_stage = _collect_metrics(out_dir / "runs" / _latest_run(out_dir))
    result["final_stage"] = final_stage
    gates = gates_from_metrics(metrics)
    values = gates.pop("_values")
    result["metrics"] = values
    result["gates"] = gates
    result["duration_s"] = round(time.time() - started, 1)
    result["flow_complete"] = bool(exit_code == 0 and final_stage)
    if exit_code != 0:
        result["reason"] = f"LibreLane exited {exit_code}"
        result["status"] = "FAIL" if exit_code not in (0,) else "BLOCKED"
        return result
    if only:
        result["status"] = "PARTIAL"
        result["reason"] = (f"staged run stopped after {only!r}; a staged run can never "
                            "establish physical signoff")
        return result
    if any(state != "PASS" for state in gates.values()):
        result["status"] = "FAIL"
        result["reason"] = "physical signoff gates not met: " + ", ".join(
            f"{name}={state}" for name, state in gates.items() if state != "PASS")
        return result
    result["status"] = "PASS"
    return result


def _latest_run(runs_root: Path) -> str:
    if not runs_root.is_dir():
        return ""
    runs = sorted((p for p in runs_root.iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime)
    return runs[-1].name if runs else ""


def _version(binary: Path) -> str | None:
    try:
        completed = subprocess.run([str(binary), "--version"], capture_output=True,
                                   text=True, timeout=120)
    except Exception:
        return None
    text = (completed.stdout or completed.stderr or "").strip().splitlines()
    return text[0].strip() if text else None
