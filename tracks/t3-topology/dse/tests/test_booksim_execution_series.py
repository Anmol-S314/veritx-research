"""Phase F: production execution carries the sampled series (opt-in).

Sampling is strictly opt-in on execute_prepared_booksim: with no series
arguments the run is byte-identical to before (null series evidence, no
amendment, no publish). With a period plus both widths, execution amends
the run-local config, validates the emitted dump through the v3 reader,
publishes it to the series store, and records both digests in v4
evidence. Refusals stay fail-closed throughout.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from test_backend_booksim_execution import (  # noqa: E402
    _binary,
    _prepared,
    _real_binary,
    _requires_binary,
    _runner_for,
)
from test_backend_booksim_projection import _parents  # noqa: E402

from veritx_dse.backend import booksim_execution as bx  # noqa: E402
from veritx_dse.backend import evidence as ev  # noqa: E402
from veritx_dse.backend import channel_series as cs  # noqa: E402
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    CONFIG_FILE,
    TRACE_FILE,
    prepare_booksim_input,
)

PERIOD = 100
LINK_W = 128
FLIT_W = 128


def _doc(run_hash, **over):
    doc = {
        "schema_version": 3,
        "run_hash": run_hash,
        "sample_period_cycles": PERIOD,
        "num_windows": 2,
        "time_resets_observed": 0,
        "capacity_formula": cs.CAPACITY_FORMULA,
        "link_capacity_flits_per_cycle": 1,
        "channels": [{
            "logical_channel_id": 7,
            "flits_per_window": [10, 20],
            "window_cycles": [100, 100],
            "stalls_per_window": None,
            "queue_cycles_per_window": [5, 9],
            "arb_wait_cycles_per_window": [1, 2],
            "tx_flits_per_window": [10, 20],
            "tx_busy_cycles_per_window": [40, 40],
            "occupancy_flit_cycles_per_window": [200, 300],
            "queue_max_per_window": [7, 11],
            "arb_max_per_window": [3, 4],
            "occupancy_max_per_window": [4, 5],
        }],
        "provenance": {
            "backend": "booksim", "version": "veritx-fork",
            "binary_hash": "0" * 64, "input_hashes": ["1" * 64],
        },
    }
    doc.update(over)
    return doc


def _expect_run_hash(prepared, binary_path):
    digests = bx.prepared_file_digests(prepared)
    binary_sha = hashlib.sha256(Path(binary_path).read_bytes()).hexdigest()
    return bx.series_run_hash(
        prepared_config_sha256=digests[CONFIG_FILE],
        trace_sha256=digests[TRACE_FILE],
        binary_sha256=binary_sha, seed=prepared.seed,
        sample_period_cycles=PERIOD, link_capacity=LINK_W // FLIT_W,
        link_width_bits=LINK_W, flit_width_bits=FLIT_W)


def _series_stub(prepared, doc):
    base = _runner_for(prepared)

    def run(command, cwd, timeout):
        Path(cwd, bx.SERIES_OUTPUT_FILE).write_text(json.dumps(doc))
        return base(command, cwd, timeout)

    return run


def _sampled(tmp_path, doc=None, **kw):
    prepared = _prepared()
    binary = _binary(tmp_path)
    if doc is None:
        doc = _doc(_expect_run_hash(prepared, binary))
    params = dict(sample_period_cycles=PERIOD,
                  series_link_width_bits=LINK_W,
                  series_flit_width_bits=FLIT_W)
    params.update(kw)
    return bx.execute_prepared_booksim(
        prepared=prepared, binary=binary, run_dir=tmp_path / "run",
        timeout=30, runner=_series_stub(prepared, doc), **params)


def test_off_by_default_records_no_series(tmp_path):
    prepared = _prepared()
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "run", timeout=30,
        runner=_runner_for(prepared))
    evidence = record.evidence
    assert evidence.schema_version == ev.EVIDENCE_SCHEMA_VERSION
    assert evidence.executed_config_sha256 is None
    assert evidence.series_run_hash is None
    assert evidence.series_sample_period_cycles is None
    assert not (tmp_path / "run" / bx.SERIES_OUTPUT_FILE).exists()
    config = (tmp_path / "run" / CONFIG_FILE).read_text()
    assert config == prepared.config_text  # unamended, byte for byte


def test_sampled_run_amends_and_records_both_digests(tmp_path):
    prepared = _prepared()
    record = _sampled(tmp_path)
    evidence = record.evidence
    assert evidence.series_run_hash == _expect_run_hash(
        prepared, tmp_path / "booksim")
    assert evidence.series_sample_period_cycles == PERIOD
    assert evidence.series_link_capacity_flits_per_cycle == 1
    assert evidence.series_link_width_bits == LINK_W
    assert evidence.series_flit_width_bits == FLIT_W
    assert evidence.executed_config_sha256 != evidence.config_sha256
    amended = (tmp_path / "run" / CONFIG_FILE).read_text()
    assert amended.startswith(prepared.config_text)
    assert f"run_hash = {evidence.series_run_hash};" in amended
    assert f"sample_period_cycles = {PERIOD};" in amended
    # Round-trips through the versioned reader.
    reread = ev.ScientificBackendEvidence.from_dict(evidence.to_dict())
    assert reread == evidence


def test_sampled_run_hash_is_deterministic(tmp_path):
    first = _sampled(tmp_path / "a").evidence.series_run_hash
    second = _sampled(tmp_path / "b").evidence.series_run_hash
    assert first == second


def test_sampled_run_publishes_validated_series(tmp_path):
    store = tmp_path / "store"
    record = _sampled(tmp_path, series_store_dir=store)
    run_hash = record.evidence.series_run_hash
    published = store / run_hash / bx.SERIES_OUTPUT_FILE
    assert published.is_file()
    artifact = cs.load_series(str(published))
    assert artifact.run_hash == run_hash
    assert artifact.sample_period_cycles == PERIOD
    # The gateway serves the published run from the store layout.
    from veritx_dse.gateway import simulation_series as gateway
    table = gateway.load_table(store, run_hash, "measured")
    assert table["channels"][0]["logical_channel_id"] == 7


def test_sampled_run_refuses_transplanted_series(tmp_path):
    prepared = _prepared()
    binary = _binary(tmp_path)
    doc = _doc("f" * 64)  # a series from some other run
    with pytest.raises(bx.BookSimExecutionError, match="transplanted"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path / "run",
            timeout=30, runner=_series_stub(prepared, doc),
            sample_period_cycles=PERIOD,
            series_link_width_bits=LINK_W,
            series_flit_width_bits=FLIT_W)


def test_sampled_run_refuses_zero_windows(tmp_path):
    prepared = _prepared()
    binary = _binary(tmp_path)
    doc = _doc(_expect_run_hash(prepared, binary), num_windows=0,
               channels=[])
    with pytest.raises(bx.BookSimExecutionError, match="NO_MEASURED"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path / "run",
            timeout=30, runner=_series_stub(prepared, doc),
            sample_period_cycles=PERIOD,
            series_link_width_bits=LINK_W,
            series_flit_width_bits=FLIT_W)


def test_publish_refuses_overwriting_a_different_series(tmp_path):
    store = tmp_path / "store"
    first = _sampled(tmp_path / "a", series_store_dir=store)
    run_hash = first.evidence.series_run_hash
    prepared = _prepared()
    binary = _binary(tmp_path / "b")
    assert _expect_run_hash(prepared, binary) == run_hash
    other = _doc(run_hash)
    other["channels"][0]["flits_per_window"] = [11, 20]
    with pytest.raises(bx.BookSimExecutionError, match="different bytes"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path / "b/run",
            timeout=30, runner=_series_stub(prepared, other),
            sample_period_cycles=PERIOD,
            series_link_width_bits=LINK_W,
            series_flit_width_bits=FLIT_W,
            series_store_dir=store)


@pytest.mark.parametrize("period", [0, -100, "100", 10.5, True])
def test_bad_period_refuses(tmp_path, period):
    with pytest.raises(bx.BookSimExecutionError,
                       match="sample_period_cycles"):
        _sampled(tmp_path, sample_period_cycles=period)


@pytest.mark.parametrize("link,flit", [(0, 128), (128, 0), (-8, 128),
                                       ("128", 128), (100, 128), (128, 0)])
def test_bad_widths_refuse(tmp_path, link, flit):
    with pytest.raises(bx.BookSimExecutionError, match="series"):
        _sampled(tmp_path, series_link_width_bits=link,
                 series_flit_width_bits=flit)


def test_widths_without_a_period_refuse(tmp_path):
    prepared = _prepared()
    with pytest.raises(bx.BookSimExecutionError, match="without"):
        bx.execute_prepared_booksim(
            prepared=prepared, binary=_binary(tmp_path),
            run_dir=tmp_path / "run", timeout=30,
            runner=_runner_for(prepared),
            series_link_width_bits=LINK_W,
            series_flit_width_bits=FLIT_W)


def test_partial_series_evidence_refuses(tmp_path):
    evidence = _sampled(tmp_path).evidence
    with pytest.raises(ev.BackendEvidenceError, match="positive int"):
        dataclasses.replace(evidence, series_sample_period_cycles=None)


def test_v3_evidence_still_parses(tmp_path):
    evidence = _sampled(tmp_path).evidence
    doc = evidence.to_dict()
    v3_keys = ("executed_config_sha256", "series_run_hash",
               "series_sample_period_cycles",
               "series_link_capacity_flits_per_cycle",
               "series_link_width_bits", "series_flit_width_bits")
    assert evidence.schema_version == 4
    v3 = {k: v for k, v in doc.items() if k not in v3_keys}
    v3["schema_version"] = 3
    v3["evidence_id"] = ev.content_hash("srota/ScientificBackendEvidence",
                                        3, {k: v for k, v in v3.items()
                                            if k != "evidence_id"})
    reread = ev.ScientificBackendEvidence.from_dict(v3)
    assert reread.schema_version == 3
    assert reread.series_run_hash is None
    assert reread.to_dict() == v3


def test_injected_stub_without_a_file_skips_validation(tmp_path):
    # The stub stands in for the binary: no emitted file, nothing to
    # validate — but the amendment is still recorded (TEST_INJECTED).
    prepared = _prepared()
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "run", timeout=30,
        runner=_runner_for(prepared),
        sample_period_cycles=PERIOD,
        series_link_width_bits=LINK_W, series_flit_width_bits=FLIT_W)
    assert record.evidence.series_run_hash == _expect_run_hash(
        prepared, tmp_path / "booksim")
    assert record.evidence.execution_fidelity == bx.FIDELITY_TEST_INJECTED


@_requires_binary
def test_real_sampled_execution_publishes_and_records(tmp_path):
    # Production path on the real fork: the caller's widths come from the
    # prepared channel model (validated flows pin flit == channel width).
    _, parents = _parents()
    flit_bits = parents.packet_format.flit_width_bits
    prepared = prepare_booksim_input(parents)
    store = tmp_path / "store"
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_real_binary(), run_dir=tmp_path / "run",
        timeout=600, sample_period_cycles=100,
        series_link_width_bits=flit_bits,
        series_flit_width_bits=flit_bits, series_store_dir=store)
    evidence = record.evidence
    assert evidence.series_run_hash is not None
    assert evidence.series_sample_period_cycles == 100
    assert evidence.series_link_capacity_flits_per_cycle == 1
    assert evidence.executed_config_sha256 != evidence.config_sha256
    published = (store / evidence.series_run_hash
                 / bx.SERIES_OUTPUT_FILE)
    assert published.is_file()
    artifact = cs.load_series(str(published))
    assert artifact.run_hash == evidence.series_run_hash
    assert artifact.flits_total() > 0
    assert artifact.channels[0].has_split()


def test_reuse_key_separates_sampled_runs():
    from veritx_dse.application.federated_evaluator import (
        _REUSE_PRE_FIELDS,
        _tier1_key,
    )
    base = {"prepared_id": "a", "config_sha256": "b", "trace_sha256": "c",
            "binary_sha256": "d", "binary_size": 1, "profile_id": "e",
            "projection_semantics_version": "f", "parser_version": "g",
            "build_manifest": "h", "build_recipe_version": "i",
            "schema_version": 4, "producer_revision": "j",
            "producer_dirty": False, "producer_transport": "k",
            "producer_fidelity": "l", "seed": 0, "topology_id": "m",
            "fabric_id": "n", "traffic_id": "o", "message_id": "p",
            "question": "q", "network_clock_hz": 1,
            "series_sample_period_cycles": None,
            "series_link_capacity_flits_per_cycle": None,
            "series_link_width_bits": None,
            "series_flit_width_bits": None}
    assert "series_sample_period_cycles" in _REUSE_PRE_FIELDS
    sampled = dict(base, series_sample_period_cycles=100,
                   series_link_capacity_flits_per_cycle=1,
                   series_link_width_bits=128, series_flit_width_bits=128)
    assert _tier1_key(sampled) != _tier1_key(base)
    assert _tier1_key(dict(sampled, series_sample_period_cycles=200)) != \
        _tier1_key(sampled)
