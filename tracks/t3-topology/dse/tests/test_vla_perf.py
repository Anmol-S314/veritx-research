"""The modeled π0/Thor workload: vendored VLA-Perf data and its template.

Every number sourced from VLA-Perf is a roofline model output, not a
measurement. These tests pin the CSV row, the template's stage split, the
parser's refusal behaviour, and the registry/provenance wiring.
"""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.vla_perf import (
    VLA_PERF_COMMIT,
    VLA_PERF_UPSTREAM,
    VlaPerfMissingColumn,
    VlaPerfMissingRow,
    kv_cache_row,
    load_pi0_rows,
    network_image_row,
    stage_summary,
    summarize,
    thor_rows,
)
from veritx_dse.core.paths import REPO
from veritx_dse.product.service import (
    ProductConfig,
    ProductService,
    parse_request_doc,
)
from veritx_dse.product.workload_registry import load_registry, resolve

DATA = REPO / "tracks/t3-topology/data/vla-perf"
TEMPLATE = REPO / "tracks/t3-topology/examples/pi0_thor_modeled-v4.json"
WORKLOAD_ID = "pi0-thor-modeled"

PI0_CSV = DATA / "pi0_family_e2e_perf.csv"
IMAGE_CSV = DATA / "network_latency_images.csv"
KV_CSV = DATA / "network_latency_bidirectional_kvcache.csv"
DENOISE_CSV = DATA / "pi0_denoising_steps_action_lengths.csv"
VALIDATION_CSV = DATA / "perf_validation_vs_realtime_vla.csv"

CHECKSUMS = {
    PI0_CSV: "68e70df3ca4c7f1b8a5cb62acaa6e4d9f1b85a48c2ab1cd47b823561e2286206",
    DENOISE_CSV: "6addcecbbd4b88303fdede36ded833b4d0aaa8472c7b12c10ceb4ec2d6cdfb63",
    IMAGE_CSV: "96ac194c1627de6541f342ad01d0e4379ecb4d18b2c5c25b0978b3588cafbf74",
    KV_CSV: "8c90e5c478235943b980d2b524b7250d1ed66f7c8a577e56b6807be2cca40a8f",
    VALIDATION_CSV: "f807142651a81bea49b7fbb06fcf0fd3d6a9549b4fe9252b3dc02c6a6128f2d9",
}


def _pi0_thor_batch1():
    thor = thor_rows(load_pi0_rows(PI0_CSV))
    return next(row for row in thor if row["batch_size"] == 1)


def _template_doc():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


class TestPi0ThorRow:
    def test_thor_row_is_present_and_has_the_expected_modeled_stages(self):
        row = _pi0_thor_batch1()
        assert row["model.name"] == "pi0"
        assert row["hardware.name"] == "Jetson_AGX_Thor"
        assert row["hardware.num_chips"] == 1
        assert row["model.seq_len_inference_prefill"] == 256

        summary = stage_summary(row)
        assert summary["vision_ms"] == pytest.approx(6.062347412109375)
        assert summary["vlm_ms"] == pytest.approx(20.303090413411457)
        assert summary["action_ms"] == pytest.approx(26.199926932652797)
        assert summary["e2e_ms"] == pytest.approx(52.56536475817363)
        assert summary["e2e_ms"] == pytest.approx(
            summary["vision_ms"] + summary["vlm_ms"] + summary["action_ms"])
        assert summary["boundness"] == {
            "vision": "Mem", "vlm": "Mem", "action": "Mem"}
        assert summary["intensity"]["vision"] == pytest.approx(321.37342499720927)

    def test_thor_selection_covers_the_batch_sweep(self):
        thor = thor_rows(load_pi0_rows(PI0_CSV))
        assert [row["batch_size"] for row in thor] == [
            1, 2, 4, 8, 16, 32, 64, 128, 256, 512]

    def test_stage_summary_refuses_a_missing_stage_column(self):
        row = dict(_pi0_thor_batch1())
        del row["vlm_time_ms"]
        with pytest.raises(VlaPerfMissingColumn, match="vlm_time_ms"):
            stage_summary(row)

    def test_load_pi0_rows_refuses_a_missing_csv_column(self, tmp_path):
        with PI0_CSV.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = [
                name for name in reader.fieldnames
                if name != "action_time_ms"]
            first = next(reader)
        broken = tmp_path / "pi0_missing_action.csv"
        with broken.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerow(first)
        with pytest.raises(VlaPerfMissingColumn, match="action_time_ms"):
            load_pi0_rows(broken)


class TestNetworkRows:
    def test_image_rows_parse_for_224(self):
        rows = network_image_row(224)
        assert len(rows) == 11
        assert {row["image_resolution"] for row in rows} == {224}
        assert {row["image_size_bytes"] for row in rows} == {150528}
        dc10 = network_image_row(224, network="DC 10GbE")
        assert len(dc10) == 1
        assert dc10[0]["transfer_time_ms"] == pytest.approx(0.12644352)

    def test_compressed_image_rows_use_the_0_1x_variant(self):
        rows = network_image_row(224, compressed=True)
        assert len(rows) == 11
        assert {row["image_size_bytes"] for row in rows} == {15052}

    def test_kv_rows_parse_seq_and_dtype_from_config_text(self):
        rows = kv_cache_row(256, "fp16", network="DC 10GbE",
                            image_compressed=True)
        assert len(rows) == 6
        assert {row["seq_len"] for row in rows} == {256}
        assert {row["dtype"] for row in rows} == {"fp16"}
        pi0_224 = next(
            row for row in rows
            if "Pi0 (Gemma 2B)" in row["return_data_config"]
            and row["image_config"].startswith("224x224"))
        assert pi0_224["image_size_bytes"] == 15052
        assert pi0_224["return_size_bytes"] == 4718592
        assert pi0_224["round_trip_latency_ms"] == pytest.approx(
            pi0_224["upload_latency_ms"] + pi0_224["download_latency_ms"])

    def test_missing_rows_refuse_instead_of_returning_empty_lists(self):
        with pytest.raises(VlaPerfMissingRow, match="Orin"):
            thor_rows(load_pi0_rows(PI0_CSV), hardware="Orin")
        with pytest.raises(VlaPerfMissingRow, match="resolution=999"):
            network_image_row(999)
        # The vendored KV table contains only fp16.
        with pytest.raises(VlaPerfMissingRow, match="bf16"):
            kv_cache_row(256, "bf16")


class TestDatasetIntegrity:
    def test_csv_bytes_match_the_readme_checksums(self):
        for path, expected in CHECKSUMS.items():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path

    def test_readme_pins_upstream_commit_and_license(self):
        readme = (DATA / "README.md").read_text(encoding="utf-8")
        assert VLA_PERF_UPSTREAM in readme
        assert VLA_PERF_COMMIT in readme
        assert "2026-11-05" in readme
        assert "MIT" in readme
        assert "not hardware measurements" in readme
        assert "MIT License" in (DATA / "LICENSE-vla-perf").read_text(
            encoding="utf-8")
        assert "Apache License" in (DATA / "LICENSE-upstream-root").read_text(
            encoding="utf-8")

    def test_summarize_is_json_ready_and_declares_modeled_provenance(self):
        summary = summarize(REPO)
        json.dumps(summary)
        assert summary["measured"] is False
        assert summary["kind"] == "modeled-roofline"
        assert summary["provenance"]["commit"] == VLA_PERF_COMMIT
        assert summary["provenance"]["upstream"] == VLA_PERF_UPSTREAM
        assert len(summary["rows"]) == 10
        batch1 = summary["rows"][0]
        assert batch1["batch_size"] == 1
        assert batch1["stages"]["e2e_ms"] == pytest.approx(52.56536475817363)


class TestTemplate:
    def test_template_stages_match_the_csv_row(self):
        doc = _template_doc()
        summary = stage_summary(_pi0_thor_batch1())
        stages = {stage["stage_id"]: stage for stage in doc["compute"]["stages"]}

        assert stages["vision_encoder"]["duration_ns"] == 6062347
        assert stages["vlm_prefill"]["duration_ns"] == 20303090
        assert stages["vision_encoder"]["duration_ns"] == round(
            summary["vision_ms"] * 1_000_000)
        assert stages["vlm_prefill"]["duration_ns"] == round(
            summary["vlm_ms"] * 1_000_000)

        steps = [stages[f"action_step_{i}"] for i in range(10)]
        assert {step["duration_ns"] for step in steps} == {2619993}
        assert sum(step["duration_ns"] for step in steps) == 26_199_930
        assert abs(
            sum(stage["duration_ns"] for stage in doc["compute"]["stages"])
            - summary["e2e_ms"] * 1_000_000) <= 5

    def test_template_declares_authored_fabric_and_traffic(self):
        doc = _template_doc()
        assert doc["workload"]["tp"] == 8
        assert doc["topology"] == {
            "kind": "mesh", "side_length": 3, "concentration": 1}
        assert doc["noc_controls"] == {"link_width": 256}
        assert doc["physical"]["clock_freq_mhz"] == 1000.0
        assert doc["physical"]["process_node_nm"] == 4
        assert sum(agent["count"] for agent in doc["agents"]) == 9
        assert doc["requirements"] == []

        profiles = doc["workload"]["traffic_profiles"]
        assert len(profiles) == 9
        assert [p["payload_bytes"] for p in profiles if
                p["traffic_class"] == "camera_ingest"] == [150528]
        assert [p["payload_bytes"] for p in profiles if
                p["traffic_class"] == "vision_tokens"] == [262144] * 4
        assert [p["payload_bytes"] for p in profiles if
                p["traffic_class"] == "action_latents"] == [800] * 4

        comment = doc["_comment"]
        assert "MODELED" in comment
        assert "NOT A MEASUREMENT" in comment
        assert VLA_PERF_COMMIT in comment
        assert "AUTHORED" in comment

    def test_template_parses_and_compiles(self):
        request = parse_request_doc(_template_doc())
        compiled = FabricCompiler().compile(request)
        assert compiled.status == "COMPILED", compiled.error
        assert request.total_nodes == 9
        assert request.workload.world_size == 8
        assert len(request.compute.stages) == 12


class TestCatalog:
    def test_registry_and_catalog_include_the_modeled_workload(self, tmp_path):
        entry = resolve(REPO, WORKLOAD_ID)
        assert entry is not None
        assert entry.owners == 8
        assert entry.display_name == "π0 · modeled Thor roofline"
        assert "MODELED" in entry.description

        ids = [record.workload_id for record in load_registry(REPO)]
        assert WORKLOAD_ID in ids

        service = ProductService(
            ProductConfig(projects_root=tmp_path / "projects"))
        catalog = service.workload_catalog()["workloads"]
        row = next(
            item for item in catalog if item["workload_id"] == WORKLOAD_ID)
        assert row["display_name"] == "π0 · modeled Thor roofline"
        assert "MODELED" in row["description"]
        assert row["evaluation_support"] == "SUPPORTED"
