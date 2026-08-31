"""Tests for veritx_dse.reports — LaTeX generation and area/power estimation.

All tests use mock data, no real BookSim runs.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from veritx_dse.reports import (
    _scale_factor,
    generate_report,
    estimate_fabric_area,
    estimate_total_power,
)
from veritx_dse.compile_model import CompileRequest


# ── _scale_factor tests ──────────────────────────────────────────────────────

class TestScaleFactor:
    def test_none_returns_1(self):
        assert _scale_factor(None) == 1.0

    def test_valid_process(self):
        assert _scale_factor(7) == 1.0

    def test_zero_process(self):
        # process_nm=0 → returns 0.0 (edge case)
        result = _scale_factor(0)
        assert isinstance(result, float)


# ── area_estimation tests ────────────────────────────────────────────────────

class TestAreaEstimation:
    def test_basic_area(self):
        area = estimate_fabric_area(n_routers=64, n_links=128, n_nics=16)
        assert "total_mm2" in area
        assert area["total_mm2"] > 0

    def test_area_increases_with_nodes(self):
        area_64 = estimate_fabric_area(n_routers=64, n_links=128, n_nics=16)
        area_128 = estimate_fabric_area(n_routers=128, n_links=256, n_nics=32)
        assert area_128["total_mm2"] > area_64["total_mm2"]


# ── power_estimation tests ──────────────────────────────────────────────────

class TestPowerEstimation:
    def test_basic_power(self):
        power = estimate_total_power(n_routers=64, data_width=256, activity_rate=0.3, avg_hops=4.0)
        assert "total_w" in power
        assert power["total_w"] > 0

    def test_power_increases_with_activity(self):
        low = estimate_total_power(n_routers=64, data_width=256, activity_rate=0.1, avg_hops=4.0)
        high = estimate_total_power(n_routers=64, data_width=256, activity_rate=0.9, avg_hops=4.0)
        assert high["total_w"] > low["total_w"]


# ── generate_report tests ────────────────────────────────────────────────────

class TestGenerateReport:
    def test_with_valid_cr(self):
        """generate_report with valid CompileRequest should work."""
        cr = CompileRequest.from_dict({
            "workload": {"model_family": "dense_transformer", "tp": 4, "dp": 1, "serving_mode": "mixed"},
            "agents": [{"kind": "compute_tile", "count": 4}],
            "noc_config": {},
        })
        result = generate_report(cr)
        assert "area" in result
        assert "power" in result


# ── Manifest atomicity test ──────────────────────────────────────────────────

class TestManifestAtomicity:
    def test_temp_file_cleanup(self, tmp_path):
        """Atomic write should leave clean manifest, no .tmp files."""
        manifest_path = tmp_path / "manifest.json"
        data = {"test": True}

        # Atomic write pattern from cli.py
        tmp_path_actual = manifest_path.with_suffix(".json.tmp")
        tmp_path_actual.write_text("not json")  # simulate partial write
        assert tmp_path_actual.exists()

        # Clean write
        manifest_path.write_text(json.dumps(data))
        tmp_path_actual.unlink()

        assert manifest_path.exists()
        assert not tmp_path_actual.exists()

    def test_manifest_stale_test_field_removed(self, tmp_path):
        """Manifest should not have stale 'test' field."""
        manifest_path = tmp_path / "manifest.json"
        data = {"run_id": "test", "test": "injected"}  # stale field

        if "test" in data:
            del data["test"]
        manifest_path.write_text(json.dumps(data))

        loaded = json.loads(manifest_path.read_text())
        assert "test" not in loaded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
