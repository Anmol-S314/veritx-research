"""Wave B3.5e tests — AddressDecodeArtifact schema v2.

Non-semantic range labels, IDENTITY forwarding, target address-width
legality, hardware-only validation, and design-map equivalence.
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
    ADDRESS_DOMAIN_SIZE, ADDRESS_TRANSFORM_IDENTITY, AddressDecodeArtifact,
    AddressDecodeEntry, AddressDecodeError, derive_address_decode,
)
from veritx_dse.model.compile_model import (  # noqa: E402
    AddressMap, AddressRange,
)


def _map(*ranges):
    return AddressMap(ranges=tuple(ranges))


def _range(name, base, size, group=1):
    return AddressRange(name=name, base=base, size=size,
                        target_agent_idx=group)


def test_empty_address_map_is_legal():
    chain = build_chain()
    assert chain.ad.entries == ()
    assert chain.ad.address_transform == ADDRESS_TRANSFORM_IDENTITY
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
    chain.ad.validate_against_attachment(chain.att)


def test_validate_against_attachment_needs_no_design():
    chain = _with_hbm()
    # signature takes only the attachment
    chain.ad.validate_against_attachment(chain.att)
    with pytest.raises(AddressDecodeError, match="attachment_hash"):
        chain.ad.validate_against_attachment(
            build_chain(protocol="CHI").att)


class TestLabelRename:
    def test_rename_preserves_decode_and_fabric_hash(self):
        a = _with_hbm(name="HBM0")
        b = _with_hbm(name="dram_bank")
        assert a.cr.design_hash() != b.cr.design_hash()
        assert a.att.attachment_hash() == b.att.attachment_hash()
        assert a.ad.address_decode_hash() == b.ad.address_decode_hash()

    def test_rename_still_matches_design_map(self):
        a = _with_hbm(name="HBM0")
        b = _with_hbm(name="dram_bank")
        b.ad.validate_against(b.cr.address_map, b.att)
        # semantic comparison ignores names across revisions
        b.ad.validate_against(a.cr.address_map, a.att)


class TestAddressWidth:
    def test_32bit_target_legal_low_range(self):
        c = _with_hbm(base=0xFFFF_0000, size=0x1_0000, hbm_addr_width=32)
        assert c.ad.entries[0].base + c.ad.entries[0].size == 1 << 32

    def test_32bit_target_high_address_refused(self):
        with pytest.raises(AddressDecodeError, match="32-bit address"):
            build_chain(
                hbm_count=1, hbm_addr_width=32,
                address_map=_map(_range("HBM0", 0x1_0000_0000, 0x100)))

    def test_global_domain_overflow_refused(self):
        with pytest.raises(AddressDecodeError, match="overflow"):
            AddressDecodeEntry("A", ADDRESS_DOMAIN_SIZE - 0x10, 0x20, 1, 0)


def test_multi_instance_group_is_explicitly_unsupported():
    with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
        _with_hbm(hbm=2)


def test_nonexistent_group_refused():
    chain = build_chain()
    cr_bad = replace(chain.cr, address_map=_map(_range("X", 0, 0x100, 7)))
    with pytest.raises(AddressDecodeError, match="outside the design"):
        derive_address_decode(design=cr_bad, attachment=chain.att)


def test_map_targeting_group_with_no_endpoint_refused():
    chain = _with_hbm()
    entry = chain.ad.entries[0]
    bad = AddressDecodeArtifact(
        attachment_hash=chain.att.attachment_hash(),
        entries=(AddressDecodeEntry("X", 0, 0x100, 1,
                                    entry.target_endpoint_id),))
    with pytest.raises(AddressDecodeError, match="no attached endpoint"):
        bad.validate_against(_map(_range("Y", 0, 0x100, 7)), chain.att)


def test_decode_for_multi_instance_group_refused_at_validation():
    two = build_chain(
        hbm_count=2, derive_decode=False,
        address_map=_map(_range("HBM0", 0x0, 0x100)))
    first_hbm = next(e for e in two.att.endpoints
                     if e.agent.kind.value == "hbm_controller")
    bad = AddressDecodeArtifact(
        attachment_hash=two.att.attachment_hash(),
        entries=(AddressDecodeEntry("X", 0, 0x100, 1,
                                    first_hbm.endpoint_id),))
    with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
        bad.validate_against_attachment(two.att)


class TestEntryShape:
    def test_overlapping_ranges_refused(self):
        with pytest.raises(AddressDecodeError, match="overlap"):
            AddressDecodeArtifact(
                attachment_hash="a" * 64,
                entries=(AddressDecodeEntry("A", 0, 0x1000, 1, 0),
                         AddressDecodeEntry("B", 0x800, 0x1000, 1, 1)))

    def test_unsorted_entries_refused(self):
        with pytest.raises(AddressDecodeError, match="canonical semantic"):
            AddressDecodeArtifact(
                attachment_hash="a" * 64,
                entries=(AddressDecodeEntry("A", 0x1000, 0x100, 1, 1),
                         AddressDecodeEntry("B", 0x0, 0x100, 1, 0)))

    def test_duplicate_semantics_with_different_names_refused(self):
        with pytest.raises(AddressDecodeError, match="duplicate semantic"):
            AddressDecodeArtifact(
                attachment_hash="a" * 64,
                entries=(AddressDecodeEntry("A", 0x0, 0x100, 1, 0),
                         AddressDecodeEntry("B", 0x0, 0x100, 1, 0)))

    def test_unsupported_transform_refused(self):
        with pytest.raises(AddressDecodeError, match="address_transform"):
            AddressDecodeArtifact(
                attachment_hash="a" * 64, entries=(),
                address_transform="SUBTRACT_BASE")


class TestIdentityMutations:
    def test_semantic_mutation_changes_hash(self):
        base = _with_hbm()
        e = base.ad.entries[0]
        twins = (
            AddressDecodeArtifact(
                attachment_hash=base.ad.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", 0x2000, e.size, 1,
                                            e.target_endpoint_id),)),
            AddressDecodeArtifact(
                attachment_hash=base.ad.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", e.base, 0x2000, 1,
                                            e.target_endpoint_id),)),
            AddressDecodeArtifact(
                attachment_hash=base.ad.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", e.base, e.size, 0,
                                            e.target_endpoint_id),)),
            AddressDecodeArtifact(
                attachment_hash=base.ad.attachment_hash,
                entries=(AddressDecodeEntry("HBM0", e.base, e.size, 1,
                                            e.target_endpoint_id + 1),)),
        )
        for twin in twins:
            assert twin.address_decode_hash() != base.ad.address_decode_hash()

    def test_name_only_mutation_does_not_change_hash(self):
        base = _with_hbm(name="HBM0")
        renamed = replace(base.ad.entries[0], name="dram_bank")
        twin = AddressDecodeArtifact(
            attachment_hash=base.ad.attachment_hash, entries=(renamed,))
        assert twin.address_decode_hash() == base.ad.address_decode_hash()

    def test_attachment_parent_change_changes_hash(self):
        a = _with_hbm()
        b = build_chain(protocol="CHI", data_width=512, hbm_count=1,
                        address_map=a.cr.address_map)
        assert b.ad.attachment_hash != a.ad.attachment_hash
        assert b.ad.address_decode_hash() != a.ad.address_decode_hash()


class TestPersistence:
    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=3), "schema_version"),
        (lambda d: d.update(schema_version=1), "v1|silent migration"),
        (lambda d: d.update(address_transform="SUBTRACT_BASE"),
         "address_transform"),
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

    def test_name_tamper_is_not_a_hash_failure(self):
        chain = _with_hbm(name="HBM0")
        d = chain.ad.to_dict()
        d["entries"][0]["name"] = "renamed"
        loaded = AddressDecodeArtifact.from_dict(d)
        assert loaded.address_decode_hash() == chain.ad.address_decode_hash()

    def test_entry_roundtrip(self):
        chain = _with_hbm()
        loaded = AddressDecodeArtifact.from_dict(chain.ad.to_dict())
        assert loaded.entries == chain.ad.entries
        assert loaded.address_decode_hash() == chain.ad.address_decode_hash()
