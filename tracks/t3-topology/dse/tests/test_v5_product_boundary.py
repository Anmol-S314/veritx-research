"""V5 is understood at the product boundary but not yet materialized."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.application.errors import ControlPlaneError, ErrorCode  # noqa: E402
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.model.compile_request_v5 import migrate_v4_to_v5  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402


def test_valid_v5_document_is_typed_unsupported_not_downgraded():
    doc = json.loads((REPO / "tracks/t3-topology/examples/"
                      "qwen3_moe_tp2_ep4_16tiles-v4.json").read_text())
    request_v5 = migrate_v4_to_v5(CompileRequestV4.from_dict(doc))

    with pytest.raises(ControlPlaneError) as caught:
        parse_request_doc(request_v5.to_dict())

    assert caught.value.code == ErrorCode.UNSUPPORTED_SEMANTICS
    assert "do not yet materialize V5 artifacts" in caught.value.message
    assert dict(caught.value.details) == {
        "blocked_at": "MATERIALIZABLE", "schema_version": 5}
