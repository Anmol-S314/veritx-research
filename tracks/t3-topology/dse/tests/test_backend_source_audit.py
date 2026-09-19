"""Wave B3.8a tests — source-drift guard.

Proves the closed-world audit stays closed: every C++ config read in the
vendored BookSim fork is registered or gated, and every gate holds
against the actual rendered certified config.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    prepare_booksim_standalone,
)
from veritx_dse.backend.booksim_profile import (  # noqa: E402
    BOOKSIM_STANDALONE_PROFILE,
)
from veritx_dse.backend.serving import (  # noqa: E402
    prepare_serving_booksim,
)
from veritx_dse.backend.source_audit import (  # noqa: E402
    GATED_FIELDS, MECHANISM_JUSTIFICATIONS, SourceAuditError,
    audit_source_drift, parse_pin_gate, scan_config_reads, verify_gates,
)
from veritx_dse.core.paths import REPO  # noqa: E402

BOOKSIM_SRC = REPO / "third_party" / "booksim2" / "src"


def _rendered_values(raw: str) -> dict[str, str]:
    out = {}
    for line in raw.splitlines():
        if " = " in line and line.endswith(";"):
            key, value = line.split(" = ", 1)
            out[key] = value[:-1]
    return out


@pytest.fixture(scope="module")
def bundle():
    return make_bundle(build_chain())


class TestCurrentClosure:
    def test_every_cpp_read_is_registered_or_gated(self):
        report = audit_source_drift(BOOKSIM_SRC)
        assert report.unregistered == (), report.unregistered
        assert report.stale_gated == (), report.stale_gated
        assert report.stale_registered == (), report.stale_registered
        assert len(report.reads) == len(
            BOOKSIM_STANDALONE_PROFILE.active_names()) + len(GATED_FIELDS)

    def test_gated_overlay_covers_every_inactive_registry_entry(self):
        inactive = set(BOOKSIM_STANDALONE_PROFILE.inactive_names())
        assert inactive <= set(GATED_FIELDS)
        reads = {r.field for r in scan_config_reads(BOOKSIM_SRC)}
        registry = set(BOOKSIM_STANDALONE_PROFILE.active_names()) | inactive
        assert set(GATED_FIELDS) == inactive | (reads - registry)

    def test_every_gated_field_has_at_least_one_gate(self):
        for field, gates in GATED_FIELDS.items():
            assert gates, field
            for gate in gates:
                if parse_pin_gate(gate) is None:
                    assert gate in MECHANISM_JUSTIFICATIONS, (field, gate)
                    assert MECHANISM_JUSTIFICATIONS[gate]


class TestScanner:
    def test_catches_dot_and_arrow_syntax(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "router.cpp").write_text(
            'int a = config.GetInt("one");\n'
            'string b = config->GetStr("two");\n'
            'float c = config.GetFloat("three");\n')
        fields = {r.field for r in scan_config_reads(src)}
        assert fields == {"one", "two", "three"}

    def test_new_unregistered_read_is_flagged(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "iq_router.cpp").write_text(
            'int magic = config.GetInt("magic_performance_knob");\n')
        report = audit_source_drift(src)
        assert report.unregistered == ("magic_performance_knob",)

    def test_stale_gate_entry_is_flagged(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "router.cpp").write_text('int x = config.GetInt("one");\n')
        report = audit_source_drift(
            src, gated={"ghost_field": ("diagnostic_only",)})
        assert report.stale_gated == ("ghost_field",)

    def test_registered_but_removed_read_is_flagged(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "router.cpp").write_text('int x = config.GetInt("one");\n')
        report = audit_source_drift(src)
        assert "num_vcs" in report.stale_registered


class TestGateVerification:
    def test_standalone_rendered_config_satisfies_every_pin_gate(
            self, bundle):
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=b"0 0 0 1 1\n")
        verify_gates(_rendered_values(
            prepared.rendered.file("config.cfg").decode()))

    def test_serving_rendered_config_satisfies_every_pin_gate(
            self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        verify_gates(_rendered_values(
            prepared.rendered.file("config.cfg").decode()))

    def test_broken_pin_gate_is_detected(self, bundle):
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=b"0 0 0 1 1\n")
        values = _rendered_values(
            prepared.rendered.file("config.cfg").decode())
        values["sim_power"] = "1"
        with pytest.raises(SourceAuditError, match="does not hold"):
            verify_gates(values)

    def test_unpinned_gate_field_is_detected(self, bundle):
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=b"0 0 0 1 1\n")
        values = _rendered_values(
            prepared.rendered.file("config.cfg").decode())
        del values["sim_power"]
        with pytest.raises(SourceAuditError, match="unpinned field"):
            verify_gates(values)

    def test_unknown_mechanism_is_detected(self, tmp_path):
        from veritx_dse.backend import source_audit as sa
        original = sa.GATED_FIELDS
        try:
            sa.GATED_FIELDS = {"x": ("not_a_mechanism",)}
            with pytest.raises(SourceAuditError, match="unknown gate"):
                verify_gates({})
        finally:
            sa.GATED_FIELDS = original
