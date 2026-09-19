"""Wave B3.5d tests — AddressDecodeArtifact.

Uses the real chain builder from test_fabric_artifact so the decode table
is derived from a genuine CompileRequest address map + attachment.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_fabric_artifact import _with_hbm, build_chain  # noqa: E402

from veritx_dse.model.address_decode import (  # noqa: E402
    ADDRESS_DOMAIN_SIZE, AddressDecodeArtifact, AddressDecodeEntry,
    AddressDecodeError, derive_address_decode,
)
from veritx_dse.model.compile_model import (  # noqa: E402
    AddressMap, AddressRange,
)


def test_empty_address_map_is_legal():
    chain = build_chain()
    assert chain.ad.entries == ()
    assert chain.ad.unmatched_address_policy == "ERROR"
    loaded = AddressDecodeArtifact.from_dict(chain.ad.to_dict())
    assert loaded.address_decode_hash() == chain.ad.address_decode_hash()


def test_singleton_group_resolves_to_exact_endpoint():
    chain = _with_hbm()
    entry = chain.ad.entries[0]
    endpoint = next(e for e in chain.att.endpoints
                    if e.endpoint_id == entry.target_endpoint_id)
    assert entry.target_agent_group == 1
    assert endpoint.agent.group_index == 1
    chain.ad.validate_against(chain.cr.address_map, chain.att)


def test_multi_instance_group_is_explicitly_unsupported():
    with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
        _with_hbm(hbm=2)


def test_nonexistent_group_refused():
    chain = build_chain()
    cr_bad = replace(chain.cr, address_map=AddressMap(ranges=(
        AddressRange(name="X", base=0, size=0x100, target_agent_idx=7),)))
    with pytest.raises(AddressDecodeError, match="outside the design"):
        derive_address_decode(design=cr_bad, attachment=chain.att)


def test_decode_against_map_with_no_endpoints_refused():
    chain = build_chain()
    # a hand-built (hash-valid) decode for a group with no attachment
    bad = AddressDecodeArtifact(
        attachment_hash=chain.att.attachment_hash(),
        entries=(AddressDecodeEntry("X", 0, 0x100, 7, 0),))
    with pytest.raises(AddressDecodeError, match="no attached endpoint"):
        bad.validate_against(
            AddressMap(ranges=(AddressRange(name="X", base=0, size=0x100,
                                           target_agent_idx=7),)),
            chain.att)


def test_decode_for_multi_instance_group_refused_at_validation():
    chain = _with_hbm(hbm=1)
    two = build_chain(
        hbm_count=2, derive_decode=False,
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x0, size=0x100,
                         target_agent_idx=1),)))
    bad = AddressDecodeArtifact(
        attachment_hash=two.att.attachment_hash(),
        entries=(AddressDecodeEntry("X", 0, 0x100, 1, 0),))
    with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
        bad.validate_against(two.cr.address_map, two.att)


def test_overlapping_ranges_refused():
    with pytest.raises(AddressDecodeError, match="overlap"):
        AddressDecodeArtifact(
            attachment_hash="a" * 64,
            entries=(AddressDecodeEntry("A", 0, 0x1000, 1, 0),
                     AddressDecodeEntry("B", 0x800, 0x1000, 1, 1)))


def test_overflow_refused():
    with pytest.raises(AddressDecodeError, match="overflow"):
        AddressDecodeEntry("A", ADDRESS_DOMAIN_SIZE - 10, 100, 1, 0)


def test_unsorted_and_duplicate_entries_refused():
    with pytest.raises(AddressDecodeError, match="canonical order"):
        AddressDecodeArtifact(
            attachment_hash="a" * 64,
            entries=(AddressDecodeEntry("B", 0x1000, 0x100, 1, 1),
                     AddressDecodeEntry("A", 0x0, 0x100, 1, 0)))
    with pytest.raises(AddressDecodeError, match="duplicate|canonical"):
        AddressDecodeArtifact(
            attachment_hash="a" * 64,
            entries=(AddressDecodeEntry("A", 0x0, 0x100, 1, 0),
                     AddressDecodeEntry("A", 0x0, 0x100, 1, 0)))


class TestIdentityMutations:
    def test_each_entry_mutation_changes_hash(self):
        chain = _with_hbm()
        base = chain.ad
        twins = (
            AddressDecodeArtifact(
                attachment_hash=base.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", 0x2000, 0x1000, 1,
                                            base.entries[0].target_endpoint_id),)),
            AddressDecodeArtifact(
                attachment_hash=base.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", 0x1000, 0x2000, 1,
                                            base.entries[0].target_endpoint_id),)),
            AddressDecodeArtifact(
                attachment_hash=base.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", 0x1000, 0x1000, 0,
                                            base.entries[0].target_endpoint_id),)),
            AddressDecodeArtifact(
                attachment_hash=base.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", 0x1000, 0x1000, 1,
                                            base.entries[0].target_endpoint_id + 1),)),
        )
        for twin in twins:
            assert twin.address_decode_hash() != base.address_decode_hash()

    def test_attachment_parent_change_changes_hash(self):
        a = _with_hbm()
        b = build_chain(protocol="CHI", data_width=512, hbm_count=1,
                        address_map=a.cr.address_map)
        assert b.ad.attachment_hash != a.ad.attachment_hash
        assert b.ad.address_decode_hash() != a.ad.address_decode_hash()


class TestPersistence:
    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(unmatched_address_policy="DROP"),
         "unmatched_address_policy"),
        (lambda d: d.update(address_decode_hash="0" * 64),
         "does not match content"),
        (lambda d: d.update(attachment_hash=""), "attachment_hash"),
    ])
    def test_persisted_mutations_refused(self, mutate, match):
        chain = _with_hbm()
        d = chain.ad.to_dict()
        mutate(d)
        with pytest.raises(AddressDecodeError, match=match):
            AddressDecodeArtifact.from_dict(d)

    def test_missing_hash_refused(self):
        chain = _with_hbm()
        d = chain.ad.to_dict()
        del d["address_decode_hash"]
        with pytest.raises(AddressDecodeError, match="address_decode_hash"):
            AddressDecodeArtifact.from_dict(d)

    def test_entry_roundtrip(self):
        chain = _with_hbm()
        loaded = AddressDecodeArtifact.from_dict(chain.ad.to_dict())
        assert loaded.entries == chain.ad.entries
        assert loaded.address_decode_hash() == chain.ad.address_decode_hash()
