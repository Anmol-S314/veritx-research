"""First-class Srota fabric intent (§5.1).

Architectural intent only: every valid combination describes a fabric the
spec admits; every invalid combination refuses with a typed error. No
simulator knobs, no invented defaults, no silent canonicalization beyond
ordering (planes/shapes/columns are sets and bitmaps, so sorted order is
the canonical form, not a default).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.srota_intent import (  # noqa: E402
    SrotaIntent,
    SrotaIntentError,
    SrotaPathShape,
    SrotaPlane,
    SrotaVCPolicy,
)


def _full(**over):
    base = {
        "side_length": 16,
        "concentration": 4,
        "mecs_row": True,
        "mecs_col": True,
        "drop_latency": 1,
        "planes": ["d", "c", "t"],
        "island_columns": [1, 8],
        "path_shapes": ["row", "column", "valiant"],
        "vc_policy": "rank",
        "sidebuf_enable": True,
        "sidebuf_watermark": 4,
        "tel_period": 4,
        "tel_latency": 8,
    }
    base.update(over)
    return base


def test_reference_fabric_builds():
    intent = SrotaIntent.from_dict(_full())
    assert intent.side_length == 16
    assert intent.concentration == 4
    assert intent.planes == frozenset(
        {SrotaPlane.DATA, SrotaPlane.CONTROL, SrotaPlane.TELEMETRY})
    assert intent.island_columns == (1, 8)
    assert intent.kind == "srota"


def test_mecs_off_fabric_builds():
    intent = SrotaIntent.from_dict(_full(
        mecs_row=False, mecs_col=False, island_columns=[]))
    assert intent.mecs_row is False
    assert intent.island_columns == ()


def test_row_only_mecs_without_islands_builds():
    intent = SrotaIntent.from_dict(_full(mecs_col=False, island_columns=[]))
    assert (intent.mecs_row, intent.mecs_col) == (True, False)


def test_round_trip_identity():
    intent = SrotaIntent.from_dict(_full())
    again = SrotaIntent.from_dict(intent.to_dict())
    assert again == intent
    assert again.intent_id() == intent.intent_id()


def test_intent_id_moves_with_content():
    a = SrotaIntent.from_dict(_full())
    b = SrotaIntent.from_dict(_full(drop_latency=2))
    assert a.intent_id() != b.intent_id()
    assert a.intent_id().startswith("sha256:")


def test_collection_order_is_canonical():
    a = SrotaIntent.from_dict(_full(
        planes=["t", "d", "c"], path_shapes=["valiant", "row", "column"],
        island_columns=[8, 1]))
    b = SrotaIntent.from_dict(_full())
    assert a == b
    assert a.to_dict()["planes"] == ["c", "d", "t"]
    assert a.to_dict()["island_columns"] == [1, 8]


def test_bad_radix_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(side_length=1))


def test_unit_concentration_refuses():
    # Plane D is a concentrated mesh; c=1 declares a plain mesh instead.
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(concentration=1))


def test_bad_drop_latency_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(drop_latency=3))


def test_empty_path_shapes_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(path_shapes=[]))


def test_unknown_path_shape_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(path_shapes=["row", "diagonal"]))


def test_unknown_vc_policy_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(vc_policy="magic"))


def test_fabric_without_data_plane_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(planes=["c", "t"]))


def test_unknown_plane_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(planes=["d", "x"]))


def test_island_column_outside_fabric_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(side_length=4, island_columns=[4]))


def test_negative_island_column_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(island_columns=[-1]))


def test_duplicate_island_column_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(island_columns=[1, 1]))


def test_islands_without_full_mecs_refuse():
    with pytest.raises(SrotaIntentError, match="express"):
        SrotaIntent.from_dict(_full(mecs_col=False))
    with pytest.raises(SrotaIntentError, match="express"):
        SrotaIntent.from_dict(_full(mecs_row=False))


def test_sidebuf_watermark_without_enable_refuses():
    with pytest.raises(SrotaIntentError, match="sidebuf"):
        SrotaIntent.from_dict(
            _full(sidebuf_enable=False, sidebuf_watermark=4))


def test_sidebuf_enable_without_watermark_refuses():
    with pytest.raises(SrotaIntentError, match="watermark"):
        SrotaIntent.from_dict(
            _full(sidebuf_enable=True, sidebuf_watermark=None))


def test_sidebuf_watermark_minimum_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(
            _full(sidebuf_enable=True, sidebuf_watermark=0))


def test_zero_telemetry_period_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(tel_period=0))


def test_debug_knobs_are_not_intent():
    for knob in ("srota_cong_thresh", "srota_epoch_len", "num_vcs",
                 "vc_buf_size", "vc_allocator", "seed", "sample_period",
                 "routing_delay"):
        with pytest.raises(SrotaIntentError, match="unknown fields"):
            SrotaIntent.from_dict(dict(_full(), **{knob: 1}))


def test_non_dict_refuses():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict([("side_length", 16)])


def test_missing_field_refuses():
    doc = _full()
    del doc["tel_latency"]
    with pytest.raises(SrotaIntentError, match="missing required field"):
        SrotaIntent.from_dict(doc)


def test_wrong_kind_refuses():
    with pytest.raises(SrotaIntentError, match="kind"):
        SrotaIntent.from_dict(dict(_full(), kind="mesh"))


def test_bool_is_not_an_int():
    with pytest.raises(SrotaIntentError):
        SrotaIntent.from_dict(_full(side_length=True))
