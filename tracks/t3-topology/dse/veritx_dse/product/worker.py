"""Isolated compile/search worker. Only its parent may publish to Studio."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _owned_group_shutdown(*_args):
    os.killpg(os.getpgrp(), signal.SIGKILL)


def main():
    # Linux: a gateway crash must not leave paid requests or simulations alive.
    signal.signal(signal.SIGTERM, _owned_group_shutdown)
    parent = int(sys.argv[3])
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)
    if os.getppid() != parent:
        _owned_group_shutdown()
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    source, output = map(Path, sys.argv[1:3])
    payload = json.loads(source.read_text())
    try:
        from veritx_dse.product.service import ProductConfig, ProductService
        config = payload["config"]
        for name in ("projects_root", "booksim_bin", "astra_bin", "repo_root", "ramulator_vendor_dir"):
            if config.get(name) is not None:
                config[name] = Path(config[name])
        if payload["kind"] == "COMPILE":
            service = ProductService(ProductConfig(**config))
            try:
                revision = service._compile_snapshot(payload["project_id"], payload["draft"], payload["sequence"])
                # The FROZEN payload keeps the route table. Only the served
                # HTTP projection withholds it (ProductService
                # .get_revision_compile_result). Blanking it here left
                # /revisions/{id}/route reading a table that was already gone,
                # so every pair reported "no entry" and measured traffic could
                # not be attributed to a channel.
                result = {"revision": revision}
            finally:
                service.jobs.shutdown()
        elif payload["kind"] == "AI_SEARCH":
            from veritx_dse.optimization.ai_search import run_search
            result = run_search(payload["draft"]["request"], output.parent, config)
        else:
            raise ValueError("unknown worker kind")
    except Exception as exc:
        from veritx_dse.application.errors import ControlPlaneError
        from veritx_dse.optimization.ai_search import ProviderError
        traceback.print_exc()
        if isinstance(exc, ControlPlaneError):
            error = {"code": exc.code.value, "message": exc.message}
        elif isinstance(exc, ProviderError):
            error = {"code": "EXECUTION_FAILED", "message": str(exc)}
        else:
            error = {"code": "INTERNAL_ERROR", "message": "worker failed; inspect its local log"}
        result = {"error": error}
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result))
    temporary.replace(output)


if __name__ == "__main__":
    main()
