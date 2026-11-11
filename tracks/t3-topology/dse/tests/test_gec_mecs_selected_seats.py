"""C5: the selected r02 contract's 74 seats are the real traffic endpoints.

The fabric shape is derived from the compiled bundle, not resized. This test
pins the identity the C5 run uses: 81 routers / 162 shared wires / 8 taps /
8 VCs / 128-bit flits, with 74 endpoints on 74 unique routers. It compiles
only; the full 5,476-flow simulation is the durable run under
``runs/selected-r02-gec-mecs-seats-20261111/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.product.project_top_rtl import (
    gec_mecs_shared_params_from_request,
)

REVISION = (REPO / "runs" / "studio-store" / "projects" / "projects" /
            "p-fd7e5e31be77" / "revisions" / "p-fd7e5e31be77-r02.json")

DESIGN_HASH = (
    "ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0"
)


def test_selected_r02_derives_74_seats_on_unique_routers():
    revision = json.loads(Path(REVISION).read_text())
    request = CompileRequestV4.from_dict(revision["request"])
    assert request.design_hash() == DESIGN_HASH

    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error

    params = gec_mecs_shared_params_from_request(
        request, compiled, endpoint_seats=True)
    assert params.k == 9
    assert params.router_count == 81
    assert params.shared_wires == 162
    assert params.taps_per_wire == 8
    assert params.num_vcs == 8
    assert params.flit_w == 128
    assert len(params.endpoint_routers) == 74
    assert len(set(params.endpoint_routers)) == 74
    assert all(0 <= router < 81 for router in params.endpoint_routers)
