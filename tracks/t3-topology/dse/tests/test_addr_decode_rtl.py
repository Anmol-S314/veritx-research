"""The resolved address map is emitted as a real, lintable decoder.

The decoder is the one RTL artifact that carries agent address mapping. It is
generated from the compiler's AddressDecodeArtifact, not from a UI table, so
the emitted constants are the same ranges the compiler resolved.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
    UnmatchedAddressPolicy,
)
from veritx_dse.product.addr_decode_rtl import render_addr_decode


def _artifact(entries):
    version = 4 if any(entry.selection_policy is not None for entry in entries) else 3
    return AddressDecodeArtifact(
        attachment_hash="a" * 64,
        entries=entries,
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
        schema_version=version,
    )


def _lint(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["verilator", "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "--top-module", "addr_decode", path.name],
        cwd=path.parent, capture_output=True, text=True)


def _assert_clean(path: Path) -> None:
    checked = _lint(path)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log


def test_a_fixed_and_striped_map_emits_bases_targets_and_stripes():
    artifact = _artifact((
        AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
        AddressDecodeEntry(name="STRIPE", base=0x1_0000, size=0x4000,
                           target_agent_group=0, target_endpoint_id=None,
                           selection_policy="STRIPED",
                           interleave_bytes=0x1000,
                           target_endpoint_ids=(2, 3)),
        AddressDecodeEntry(name="KV", base=0x8000_0000, size=0x4000,
                           target_agent_group=0, target_endpoint_id=1),
    ))
    source = render_addr_decode(artifact)
    assert "module addr_decode" in source
    assert "localparam logic [63:0] BASE_0 = 64'h0000000000001000;" in source
    assert "localparam logic [63:0] LAST_2 = 64'h0000000080003fff;" in source
    assert "stripe_index = (addr64 - BASE_1) >> 12;" in source
    assert "case (stripe_index % 2)" in source
    assert "target_oh[3] = 1'b1;" in source
    assert "assign miss    = ~hit;" in source
    assert "assign overlap = (hit_count > 1);" in source
    assert artifact.address_decode_hash in source


def test_the_emitted_decoder_lints_with_verilator(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the address decoder")
    artifact = _artifact((
        AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
        AddressDecodeEntry(name="STRIPE", base=0x1_0000, size=0x4000,
                           target_agent_group=0, target_endpoint_id=None,
                           selection_policy="STRIPED",
                           interleave_bytes=0x1000,
                           target_endpoint_ids=(2, 3)),
    ))
    path = tmp_path / "addr_decode.sv"
    path.write_text(render_addr_decode(artifact))
    _assert_clean(path)


def test_a_fixed_only_map_has_no_unused_stripe_signal(tmp_path):
    artifact = _artifact((
        AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
    ))
    source = render_addr_decode(artifact)
    assert "stripe_index" not in source
    if shutil.which("verilator") is not None:
        path = tmp_path / "addr_decode.sv"
        path.write_text(source)
        _assert_clean(path)


def test_a_base_zero_range_does_not_emit_a_constant_comparison(tmp_path):
    artifact = _artifact((
        AddressDecodeEntry(name="LOW", base=0, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
    ))
    source = render_addr_decode(artifact)
    assert "localparam logic [63:0] BASE_0" not in source
    assert "localparam logic [63:0] LAST_0 = 64'h0000000000000fff;" in source
    assert "assign entry_hit[0] = (addr64 <= LAST_0);" in source
    if shutil.which("verilator") is not None:
        path = tmp_path / "addr_decode.sv"
        path.write_text(source)
        _assert_clean(path)


def test_a_range_ending_at_2_to_the_64_is_emitted_without_overflow(tmp_path):
    artifact = _artifact((
        AddressDecodeEntry(name="TOP", base=0xFFFF_FFFF_FFFF_F000,
                           size=0x1000, target_agent_group=0,
                           target_endpoint_id=0),
    ))
    source = render_addr_decode(artifact)
    assert "localparam logic [63:0] BASE_0 = 64'hfffffffffffff000;" in source
    assert "localparam logic [63:0] LAST_0" not in source
    assert "assign entry_hit[0] = (addr64 >= BASE_0);" in source
    if shutil.which("verilator") is not None:
        path = tmp_path / "addr_decode.sv"
        path.write_text(source)
        _assert_clean(path)


def test_a_narrow_address_port_zero_extends_without_warnings(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the address decoder")
    artifact = _artifact((
        AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
    ))
    source = render_addr_decode(artifact, addr_width=32)
    assert "parameter int ADDR_W = 32" in source
    path = tmp_path / "addr_decode.sv"
    path.write_text(source)
    _assert_clean(path)


def test_an_empty_map_is_an_explicit_miss_not_a_pass_through(tmp_path):
    artifact = _artifact(())
    source = render_addr_decode(artifact)
    assert "assign target_oh = '0;" in source
    assert "assign hit       = 1'b0;" in source
    assert "assign miss      = 1'b1;" in source
    assert "assign overlap   = 1'b0;" in source
    if shutil.which("verilator") is not None:
        path = tmp_path / "addr_decode.sv"
        path.write_text(source)
        _assert_clean(path)


def test_overlap_is_observable_and_target_oh_is_not_one_hot_then():
    # The compiler refuses overlapping ranges, so this is a structural check
    # of the emitted decoder rather than a production map. It documents that
    # target_oh is one-hot only while overlap is low.
    entries = (
        SimpleNamespace(name="A", base=0x1000, size=0x2000,
                        target_agent_group=0, target_endpoint_id=0,
                        selection_policy=None, target_instance_index=None,
                        interleave_bytes=None, target_endpoint_ids=()),
        SimpleNamespace(name="B", base=0x2000, size=0x1000,
                        target_agent_group=0, target_endpoint_id=1,
                        selection_policy=None, target_instance_index=None,
                        interleave_bytes=None, target_endpoint_ids=()),
    )
    source = render_addr_decode(SimpleNamespace(entries=entries, address_decode_hash=""))
    assert "assign overlap = (hit_count > 1);" in source
    assert "target_oh[0] = 1'b1;" in source
    assert "target_oh[1] = 1'b1;" in source
    assert "one-hot only while overlap is low" in source
