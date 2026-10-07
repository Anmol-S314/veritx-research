from __future__ import annotations

import pytest

from veritx_dse.model.srota_shape_vc_policy import (
    SrotaShapeVCPartitionPolicy,
    SrotaShapeVCPolicyError,
)


def test_shape_policy_derives_disjoint_contiguous_ranges_and_transitions():
    policy = SrotaShapeVCPartitionPolicy.derive(5)

    assert policy.shape_to_vcs == (
        ("row", (0, 1)),
        ("column", (2, 3)),
    )
    assert policy.unused_vcs == (4,)
    assert policy.partition_to_vcs == {0: (0, 1), 1: (2, 3)}
    assert policy.allowed_transitions == (
        (0, 0), (0, 1), (1, 0), (1, 1),
        (2, 2), (2, 3), (3, 2), (3, 3),
    )
    encoded = policy.to_dict()
    assert encoded["policy_hash"] == policy.policy_hash
    assert SrotaShapeVCPartitionPolicy.from_dict(encoded) == policy


def test_shape_policy_matches_booksim_integer_split():
    policy = SrotaShapeVCPartitionPolicy.derive(3)
    assert policy.partition_to_vcs == {0: (0,), 1: (1,)}
    assert policy.unused_vcs == (2,)


@pytest.mark.parametrize("num_vcs", [0, 1, True, 2.0])
def test_shape_policy_requires_at_least_two_exact_vcs(num_vcs):
    with pytest.raises(SrotaShapeVCPolicyError, match="num_vcs"):
        SrotaShapeVCPartitionPolicy.derive(num_vcs)


def test_shape_policy_rejects_a_tampered_hash():
    encoded = SrotaShapeVCPartitionPolicy.derive(4).to_dict()
    encoded["policy_hash"] = "tampered"
    with pytest.raises(SrotaShapeVCPolicyError, match="policy_hash"):
        SrotaShapeVCPartitionPolicy.from_dict(encoded)


def test_shape_policy_rejects_boolean_vc_ids():
    with pytest.raises(SrotaShapeVCPolicyError, match="integer VC"):
        SrotaShapeVCPartitionPolicy(
            num_vcs=2,
            shape_to_vcs=(("row", (False,)), ("column", (1,))),
            unused_vcs=(),
        )


def test_shape_policy_rejects_a_tampered_partition():
    policy = SrotaShapeVCPartitionPolicy.derive(4)
    with pytest.raises(SrotaShapeVCPolicyError, match="canonical"):
        SrotaShapeVCPartitionPolicy(
            num_vcs=4,
            shape_to_vcs=(("row", (0, 1, 2)), ("column", (3,))),
            unused_vcs=(),
        )
