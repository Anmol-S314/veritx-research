"""Measured per-channel load (§20.1): fork emission + typed reader.

The BookSim fork emits a versioned channel-activity dump; the reader joins
it to the certified channel table into a MEASURED_CHANNEL_LOAD artifact
that shares no type with DERIVED expected load. Refusal cases pin the
fail-closed rules: unknown schema, ragged vectors, ambiguous ports,
and missing keys never parse into a measurement.

The end-to-end test drives the REAL binary on an in-repo config: measured
flits must conserve exactly (attributed + unmatched == emitted), and an
empty channel table must attribute nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.backend.channel_measurements import (  # noqa: E402
    CHANNEL_ACTIVITY_SCHEMA,
    ChannelMeasurementError,
    read_measured_load,
)
from veritx_dse.core.paths import BOOKSIM_BIN  # noqa: E402

CONFIG = (REPO / "tracks/t3-topology/configs/cmesh16.cfg")


def _doc(**over):
    doc = {
        "schema": CHANNEL_ACTIVITY_SCHEMA,
        "subnet": 0,
        "router_count": 1,
        "routers": [{
            "id": 0,
            "num_inputs": 2,
            "num_outputs": 2,
            "num_classes": 1,
            "cycles_observed": 100,
            "output_activity": [
                {"port": 0, "flits_by_class": [10]},
                {"port": 1, "flits_by_class": [0]},
            ],
            "input_activity": [],
        }],
        "skipped_non_iq_routers": 0,
    }
    doc.update(over)
    return doc


def _channels():
    return [
        {"channel_id": 0, "src_router": 0, "src_port": 0, "dst_router": 1},
    ]


def test_attributes_counters_to_the_certified_channel():
    load = read_measured_load(_doc(), _channels())
    assert load.kind == "MEASURED_CHANNEL_LOAD"
    assert load.schema == CHANNEL_ACTIVITY_SCHEMA
    assert [(c.channel_id, c.flits) for c in load.channels] == [(0, 10)]
    assert load.channels[0].flits_by_class == (10,)
    assert load.unmatched_ports == ((0, 1, 0),)
    assert load.skipped_non_iq_routers == 0


def test_empty_channel_table_attributes_nothing():
    load = read_measured_load(_doc(), [])
    assert load.channels == ()
    assert load.flits_total() == 0
    # Both ports reported, none attributed, none lost.
    assert sorted(load.unmatched_ports) == [(0, 0, 10), (0, 1, 0)]


def test_unknown_schema_refuses():
    with pytest.raises(ChannelMeasurementError, match="not.*v1"):
        read_measured_load(_doc(schema="veritx/channel-activity/v9"), [])


def test_missing_key_refuses():
    doc = _doc()
    del doc["routers"]
    with pytest.raises(ChannelMeasurementError, match="missing 'routers'"):
        read_measured_load(doc, [])


def test_ragged_per_class_vector_refuses():
    doc = _doc()
    doc["routers"][0]["output_activity"][0]["flits_by_class"] = [10, 5]
    with pytest.raises(ChannelMeasurementError, match="per-class vector"):
        read_measured_load(doc, [])


def test_negative_count_refuses():
    doc = _doc()
    doc["routers"][0]["output_activity"][0]["flits_by_class"] = [-1]
    with pytest.raises(ChannelMeasurementError, match="per-class vector"):
        read_measured_load(doc, [])


def test_ambiguous_port_refuses_rather_than_splitting():
    channels = [
        {"channel_id": 0, "src_router": 0, "src_port": 0, "dst_router": 1},
        {"channel_id": 1, "src_router": 0, "src_port": 0, "dst_router": 2},
    ]
    with pytest.raises(ChannelMeasurementError, match="twice"):
        read_measured_load(_doc(), channels)


def test_non_object_document_refuses():
    with pytest.raises(ChannelMeasurementError, match="must be an object"):
        read_measured_load([1, 2, 3], [])


def test_measured_and_expected_load_share_no_type():
    """The artifact carries its kind explicitly: a consumer cannot mistake
    measured counters for derived expectations without reading the label."""
    load = read_measured_load(_doc(), _channels())
    assert load.kind == "MEASURED_CHANNEL_LOAD"
    assert load.kind != "DERIVED_EXPECTED_LOAD"


def _run_booksim(cfg: Path, out: Path, activity: Path | None) -> None:
    cmd = [str(BOOKSIM_BIN), str(cfg)]
    if activity is not None:
        cmd.append(f"channel_activity_output={activity}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          cwd=str(out.parent))
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_end_to_end_measured_load_conserves(tmp_path):
    """Real binary, real counters: attributed + unmatched == emitted."""
    if not Path(BOOKSIM_BIN).is_file():
        pytest.skip("booksim binary absent")
    activity = tmp_path / "activity.json"
    _run_booksim(CONFIG, tmp_path / "run.log", activity)
    doc = json.loads(activity.read_text())
    assert doc["schema"] == CHANNEL_ACTIVITY_SCHEMA
    assert doc["skipped_non_iq_routers"] == 0
    emitted = sum(
        sum(o["flits_by_class"])
        for r in doc["routers"] for o in r["output_activity"])
    assert emitted > 0, "the run moved no flits — not a measurement"
    load = read_measured_load(doc, [])
    accounted = load.flits_total() + sum(
        f for _, _, f in load.unmatched_ports)
    assert accounted == emitted
    # Every emitted port is either attributed or reported.
    assert len(load.unmatched_ports) == sum(
        len(r["output_activity"]) for r in doc["routers"])


def test_end_to_end_default_run_emits_no_artifact(tmp_path):
    """Key absent: the binary must not write anything extra."""
    if not Path(BOOKSIM_BIN).is_file():
        pytest.skip("booksim binary absent")
    _run_booksim(CONFIG, tmp_path / "run.log", None)
    assert list(tmp_path.glob("*.json")) == []
