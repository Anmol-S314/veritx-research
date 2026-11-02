"""Desktop-only gateway host. The browser deployment is unchanged."""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import runpy
import secrets
import socket
import sys
import threading

REPO = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[4]
DSE = REPO / "tracks" / "t3-topology" / "dse"
# Preserve the repository layout: several registries and workers use __file__.
sys.path.insert(0, str(DSE))


def configure_storage(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    data_dir.chmod(0o700)
    for key, relative in {
        "VERITX_STORE_ROOT": "store",
        "VERITX_RUNS_ROOT": "runs",
        "VERITX_PROJECTS_ROOT": "projects",
        "VERITX_REVISIONS_ROOT": "revisions",
        # Ablation search writes its run directory; keep it out of the
        # root-owned install prefix.
        "VERITX_ABLATION_ROOT": "ablation-runs",
    }.items():
        os.environ[key] = str(data_dir / relative)
    # Record sampled counters and the observed flit capture by default.
    # Without this a menu-launched app reports "Not recorded" for every counter
    # and "no observed watch capture" for every historical bundle, because the
    # only way to switch sampling on is an environment variable nobody can
    # guess from inside the UI. Sampling is a RECORDING setting, not a
    # simulation one: booksim_execution.amend_config_for_series appends its keys
    # after the prepared config, so the prepared identity and the simulated
    # outcome are unchanged.
    #
    # Only the PERIOD is defaulted. The two widths are deliberately left unset
    # and derived per run from the compiled fabric's own declared
    # channel/shared-link width_bits and packet-format flit_width_bits
    # (application/series_widths.py), because a width guessed here could
    # disagree with the fabric and fabricate utilization.
    os.environ.setdefault("VERITX_SERIES_SAMPLE_PERIOD", "10")


def desktop_app(token: str):
    from starlette.applications import Starlette
    from starlette.middleware.cors import CORSMiddleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.routing import Mount
    from veritx_dse.gateway.app import app as gateway

    @asynccontextmanager
    async def lifespan(_app):
        async with gateway.router.lifespan_context(gateway):
            yield

    app = Starlette(
        routes=[Mount(f"/{token}/gw", app=gateway)],
        lifespan=lifespan,
    )
    # A path capability also works for EventSource, downloads and artifact URLs,
    # which cannot all carry custom Authorization headers. Never log these URLs.
    app = CORSMiddleware(
        app,
        allow_origins=[
            "tauri://localhost", "http://tauri.localhost",
            "http://127.0.0.1:5174",
        ],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["accept", "content-type"],
        # Cross-origin from the webview (tauri://localhost -> 127.0.0.1), so
        # non-safelisted response headers are invisible to JS unless exposed
        # here. Without x-content-sha256 the artifact verifier reads null and
        # refuses every bundle as "bytes do not match the recorded manifest".
        expose_headers=["x-content-sha256"],
    )
    return TrustedHostMiddleware(app, allowed_hosts=["127.0.0.1"])


def python_child(argv: list[str]) -> bool:
    """Keep existing Python worker / Ramulator subprocess contracts frozen."""
    if not argv:
        return False
    if argv[0] == "-c" and len(argv) >= 2:
        sys.argv = ["-c", *argv[2:]]
        exec(argv[1], {"__name__": "__main__"})
        return True
    if argv[0] == "-m" and len(argv) >= 2:
        sys.argv = argv[1:]
        runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        return True
    if argv[0].endswith(".py"):
        sys.argv = argv
        # `python script.py` puts the script's own directory first on sys.path;
        # runpy.run_path does not. Scripts that import a sibling module rely on
        # that (ablate_workloads.py does `from ablation_evidence import ...`), and
        # inside the frozen app the import failed, so every ablation answered
        # 'the runner produced no ablation.json'. Mirror the interpreter.
        script_dir = str(Path(argv[0]).resolve().parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        runpy.run_path(argv[0], run_name="__main__")
        return True
    return False


def main() -> None:
    if python_child(sys.argv[1:]):
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    if os.name == "nt":
        from veritx_dse.core.windows_job import contain_current_process
        contain_current_process()
    configure_storage(args.data_dir.resolve())

    import uvicorn

    token = secrets.token_urlsafe(32)
    # Bind port 0 once and pass the same socket to uvicorn: no port-picking race.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]

    class DesktopServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                print("SROTA_READY " + json.dumps({
                    "base": f"http://127.0.0.1:{port}/{token}/gw",
                }), flush=True)

    server = DesktopServer(uvicorn.Config(
        desktop_app(token), access_log=False, log_level="warning",
        loop="asyncio", http="h11", ws="none",
        timeout_graceful_shutdown=5,
        headers=[("referrer-policy", "no-referrer"), ("cache-control", "no-store")],
    ))

    def parent_closed():
        # Tauri owns this pipe. Even a crashed desktop process closes it.
        sys.stdin.buffer.read()
        server.should_exit = True

    threading.Thread(target=parent_closed, daemon=True).start()
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
