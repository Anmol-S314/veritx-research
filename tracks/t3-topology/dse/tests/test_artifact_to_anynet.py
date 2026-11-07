from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE_ROOT = Path(__file__).resolve().parents[1]
RTLGEN_DIR = DSE_ROOT.parent / "scripts" / "rtlgen"
if str(DSE_ROOT) not in sys.path:
    sys.path.insert(0, str(DSE_ROOT))
if str(RTLGEN_DIR) not in sys.path:
    sys.path.insert(0, str(RTLGEN_DIR))

from artifact_to_anynet import ArtifactRtlRefusal, artifact_to_anynet, main
from veritx_dse.model.topology_artifact import (
    MaterializedFamily,
    materialize_family,
    materialize_flatfly,
    materialize_gec_express,
    materialize_gec_mecs,
)
from veritx_dse.core.anynet import parse_anynet_file


def roundtrip(artifact, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "topology.anynet"
    path.write_text(artifact_to_anynet(artifact.to_dict()))
    return parse_anynet_file(path)


def test_ring_artifact_lowers_to_connected_anynet(tmp_path):
    artifact = materialize_family(
        MaterializedFamily.RING, endpoint_count=16, radix=16)
    graph = roundtrip(artifact, tmp_path)
    assert graph.n_routers == 16
    assert graph.n_nodes == 16
    assert graph.n_edges == 16
    assert graph.is_symmetric


def test_mesh_flatfly_and_gec_express_lower_without_losing_edges(tmp_path):
    cases = [
        materialize_family(MaterializedFamily.MESH, endpoint_count=16, radix=4),
        materialize_family(MaterializedFamily.TORUS, endpoint_count=16, radix=4),
        materialize_flatfly(k=4, n=2),
        materialize_gec_express(k=4),
    ]
    for index, artifact in enumerate(cases):
        graph = roundtrip(artifact, tmp_path / str(index))
        assert graph.n_routers == artifact.router_count
        assert graph.n_edges == len(artifact.channels) // 2
        assert graph.is_symmetric


def test_mecs_shared_link_artifact_is_refused():
    artifact = materialize_gec_mecs(k=4, concentration=1, o=1, d=3)
    with pytest.raises(ArtifactRtlRefusal, match="shared/multidrop"):
        artifact_to_anynet(artifact.to_dict())


def test_concentrated_mesh_is_refused_instead_of_losing_terminals():
    artifact = materialize_family(
        MaterializedFamily.CONCENTRATED_MESH,
        endpoint_count=16, concentration=4, radix=2)
    with pytest.raises(ArtifactRtlRefusal, match="one terminal per router"):
        artifact_to_anynet(artifact.to_dict())


def test_cli_refuses_nonempty_output_directory_without_overwriting(tmp_path, capsys):
    artifact = materialize_family(
        MaterializedFamily.RING, endpoint_count=8, radix=8)
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps(artifact.to_dict()))
    outdir = tmp_path / "out"
    outdir.mkdir()
    sentinel = outdir / "keep.txt"
    sentinel.write_text("keep")

    assert main([str(artifact_path), "--outdir", str(outdir)]) == 2
    assert sentinel.read_text() == "keep"
    assert "output directory is not empty" in capsys.readouterr().err


def test_nondefault_channel_width_and_latency_are_refused():
    for kwargs, message in [
        ({"width_bits": 128}, "width is 128"),
        ({"latency_cycles": 2}, "latency is 2"),
    ]:
        artifact = materialize_family(
            MaterializedFamily.RING, endpoint_count=8, radix=8, **kwargs)
        with pytest.raises(ArtifactRtlRefusal, match=message):
            artifact_to_anynet(artifact.to_dict())
