"""Access policy tests — the five-rung ladder must stay separated.

The load-bearing claim under test is Scenario G: a target can be *network
reachable* and simultaneously *access forbidden*, and those are two distinct
facts. Collapsing them (or coercing an unevaluated rung to ``False``) is the
bug this file exists to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.access_policy import (  # noqa: E402
    ACCESS_POLICY_SCHEMA_VERSION,
    AccessDecision,
    AccessPermission,
    AccessPolicyArtifact,
    AccessPolicyError,
    AccessRule,
    AddressSpace,
    UnmatchedAccessPolicy,
)

_TAG = "srota/AccessPolicyArtifact"


def _rule(rule_id="r0", initiator="cpu0", target="mem0", base=0, size=0x1000,
          permission=AccessPermission.RW, space=AddressSpace.GLOBAL) -> AccessRule:
    return AccessRule(rule_id=rule_id, initiator=initiator, target=target,
                      address_base=base, address_size=size,
                      permission=permission, address_space=space)


def _policy(*rules, unmatched=UnmatchedAccessPolicy.DENY) -> AccessPolicyArtifact:
    return AccessPolicyArtifact(rules=tuple(rules), unmatched_policy=unmatched)


# Canonical order for these fixtures: (initiator, target, base, size, id).
def _two_disjoint():
    return _policy(
        _rule("r0", base=0x0, size=0x1000, permission=AccessPermission.RO),
        _rule("r1", base=0x1000, size=0x1000, permission=AccessPermission.WO),
    )


# ---------------------------------------------------------------- roundtrip --

def test_roundtrip_fully_populated():
    policy = AccessPolicyArtifact(
        rules=(
            _rule("r0", base=0x0, size=0x1000, permission=AccessPermission.RO),
            _rule("r1", initiator="cpu1", target="mem1", base=0x0,
                  size=0x400, permission=AccessPermission.DENY),
            _rule("r2", initiator="cpu1", target="mem1", base=0x400,
                  size=0x400, permission=AccessPermission.WO,
                  space=AddressSpace.LOCAL),
        ),
        unmatched_policy=UnmatchedAccessPolicy.ALLOW,
    )
    back = AccessPolicyArtifact.from_dict(policy.to_dict())
    assert back == policy
    assert back.policy_hash == policy.policy_hash


def test_roundtrip_empty_policy():
    policy = _policy()
    assert AccessPolicyArtifact.from_dict(policy.to_dict()) == policy
    assert policy.rules == ()


def test_rule_roundtrip_and_decision_roundtrip():
    rule = _rule("r7", permission=AccessPermission.DENY,
                 space=AddressSpace.LOCAL)
    assert AccessRule.from_dict(rule.to_dict()) == rule

    decision = AccessDecision(
        endpoint_exists=True, route_exists=False, window_matched=True,
        permission=AccessPermission.RO, observed=None, rule_id="r7",
        reason="reachable but forbidden", permitted=False)
    assert AccessDecision.from_dict(decision.to_dict()) == decision


def test_to_dict_carries_type_tag_and_hash():
    d = _two_disjoint().to_dict()
    assert d["type"] == _TAG
    assert d["schema_version"] == ACCESS_POLICY_SCHEMA_VERSION
    assert d["unmatched_policy"] == "DENY"
    assert len(d["policy_hash"]) == 64


# ----------------------------------------------------------- strict loading --

def test_unknown_key_refuses_on_all_three_from_dict():
    with pytest.raises(AccessPolicyError, match="unknown fields"):
        AccessPolicyArtifact.from_dict(
            {"type": _TAG, "rules": [], "unmatched_policy": "DENY",
             "schema_version": 1, "policy_hash": "x", "firewall": True})
    with pytest.raises(AccessPolicyError, match="unknown fields"):
        AccessRule.from_dict({**_rule().to_dict(), "trust_level": 3})
    with pytest.raises(AccessPolicyError, match="unknown fields"):
        AccessDecision.from_dict({"permission": None, "reason": "r",
                                  "zero_trust": True})


def test_missing_required_field_refuses():
    with pytest.raises(AccessPolicyError, match="missing required field"):
        AccessRule.from_dict({"rule_id": "r0", "initiator": "a",
                              "target": "b", "address_base": 0})
    with pytest.raises(AccessPolicyError, match="missing required field"):
        AccessPolicyArtifact.from_dict({"type": _TAG})


def test_non_object_refuses():
    with pytest.raises(AccessPolicyError, match="must be an object"):
        AccessPolicyArtifact.from_dict(["not", "a", "dict"])


def test_wrong_type_tag_refuses():
    with pytest.raises(AccessPolicyError, match="must be 'srota/AccessPolicy"):
        AccessPolicyArtifact.from_dict({"type": "srota/Other", "rules": []})


def test_unsupported_schema_version_refuses():
    with pytest.raises(AccessPolicyError, match="schema_version"):
        AccessPolicyArtifact(rules=(), schema_version=2)


def test_policy_hash_mismatch_refuses():
    d = _two_disjoint().to_dict()
    d["policy_hash"] = "0" * 64
    with pytest.raises(AccessPolicyError, match="does not match content"):
        AccessPolicyArtifact.from_dict(d)


def test_unknown_enum_values_refuse():
    with pytest.raises(AccessPolicyError, match="unknown permission"):
        AccessRule.from_dict({**_rule().to_dict(), "permission": "RWX"})
    with pytest.raises(AccessPolicyError, match="unknown address_space"):
        AccessRule.from_dict({**_rule().to_dict(), "address_space": "GLOBAL_"})
    with pytest.raises(AccessPolicyError, match="unknown unmatched_policy"):
        AccessPolicyArtifact.from_dict({"type": _TAG, "rules": [],
                                        "unmatched_policy": "MAYBE"})
    with pytest.raises(AccessPolicyError, match="permission must be a"):
        _rule(permission="RW")


# ------------------------------------------------------------- the laws -----

def test_overlapping_windows_for_same_pair_refuse_and_name_both_rules():
    with pytest.raises(AccessPolicyError) as exc:
        _policy(
            _rule("alpha", base=0x0, size=0x2000),
            _rule("beta", base=0x1000, size=0x2000),
        )
    msg = str(exc.value)
    assert "alpha" in msg and "beta" in msg
    assert "overlap" in msg
    assert "[0, 8192)" in msg and "[4096, 12288)" in msg


def test_identical_windows_refuse():
    with pytest.raises(AccessPolicyError, match="overlap"):
        _policy(_rule("a", base=0x0, size=0x1000),
                _rule("b", base=0x0, size=0x1000))


def test_windows_for_different_initiators_do_not_collide():
    policy = _policy(
        _rule("a", initiator="cpu0", base=0x0, size=0x1000),
        _rule("b", initiator="cpu1", base=0x0, size=0x1000),
    )
    assert len(policy.rules) == 2


def test_windows_in_different_spaces_do_not_collide():
    policy = _policy(
        _rule("a", base=0x0, size=0x1000),
        _rule("b", base=0x0, size=0x1000, space=AddressSpace.LOCAL),
    )
    assert len(policy.rules) == 2


def test_rule_id_must_be_unique():
    with pytest.raises(AccessPolicyError, match="unique"):
        _policy(_rule("same", base=0x0, size=0x100),
                _rule("same", initiator="cpu1", base=0x0, size=0x100))


def test_rules_must_be_in_canonical_order():
    with pytest.raises(AccessPolicyError, match="canonical order"):
        _policy(
            _rule("r1", initiator="cpu1", base=0x0, size=0x100),
            _rule("r0", initiator="cpu0", base=0x0, size=0x100),
        )


def test_self_grant_refuses():
    with pytest.raises(AccessPolicyError, match="permission over itself"):
        _rule("self", initiator="cpu0", target="cpu0")


def test_address_size_must_be_positive():
    with pytest.raises(AccessPolicyError, match="address_size must be >= 1"):
        _rule(size=0)
    with pytest.raises(AccessPolicyError, match="address_size must be >= 1"):
        _rule(size=-4096)


def test_address_base_must_be_non_negative():
    with pytest.raises(AccessPolicyError, match="address_base must be >= 0"):
        _rule(base=-1)


def test_exact_int_only_no_floats_or_bools():
    with pytest.raises(AccessPolicyError, match="exact int"):
        _rule(size=4096.0)
    with pytest.raises(AccessPolicyError, match="exact int"):
        _rule(base=True)


def test_range_overflowing_address_domain_refuses():
    with pytest.raises(AccessPolicyError, match="overflows the 64-bit"):
        _rule(base=(1 << 64) - 16, size=4096)


def test_unknown_operation_refuses():
    with pytest.raises(AccessPolicyError, match="unknown operation"):
        _policy(_rule(base=0x0, size=0x1000))._evaluate(
            operation="execute", initiator="cpu0", target="mem0",
            address=0, address_space=AddressSpace.GLOBAL,
            endpoint_exists=None, route_exists=None, observed=None)


# --------------------------------------------------- neutral equivalence ----

def test_unmatched_policy_defaults_to_deny():
    assert _policy().unmatched_policy is UnmatchedAccessPolicy.DENY
    assert AccessPolicyArtifact.from_dict(
        {"type": _TAG, "rules": []}).unmatched_policy \
        is UnmatchedAccessPolicy.DENY


def test_allow_must_be_authored_explicitly():
    assert AccessPolicyArtifact.from_dict(
        {"type": _TAG, "rules": [],
         "unmatched_policy": "ALLOW"}).unmatched_policy \
        is UnmatchedAccessPolicy.ALLOW


def test_absence_is_not_a_grant():
    """DENY is expressed by an explicit rule, never by absence — and an
    address in no window is denied by default, not silently permitted."""
    policy = _policy(_rule("r0", base=0x1000, size=0x1000))
    decision = policy.may_read("cpu0", "mem0", 0x0)
    assert decision.window_matched is False
    assert decision.permission is None
    assert decision.permitted is False
    assert decision.rule_id is None


def test_no_invented_permission_on_unmapped_address():
    policy = _policy(_rule("r0", base=0x1000, size=0x1000),
                     unmatched=UnmatchedAccessPolicy.ALLOW)
    decision = policy.may_write("cpu0", "mem0", 0x0)
    assert decision.window_matched is False
    assert decision.permission is None      # never fabricated
    assert decision.permitted is True       # authored unmatched ALLOW


# ------------------------------------------------------------ the ladder ----

def test_rw_allows_both_operations():
    policy = _policy(_rule("r0", base=0x0, size=0x1000,
                           permission=AccessPermission.RW))
    assert policy.may_read("cpu0", "mem0", 0x10).permitted is True
    assert policy.may_write("cpu0", "mem0", 0x10).permitted is True


def test_ro_allows_read_forbids_write():
    policy = _policy(_rule("r0", base=0x0, size=0x1000,
                           permission=AccessPermission.RO))
    assert policy.may_read("cpu0", "mem0", 0x10).permitted is True
    assert policy.may_write("cpu0", "mem0", 0x10).permitted is False


def test_wo_forbids_read_allows_write():
    policy = _policy(_rule("r0", base=0x0, size=0x1000,
                           permission=AccessPermission.WO))
    assert policy.may_read("cpu0", "mem0", 0x10).permitted is False
    assert policy.may_write("cpu0", "mem0", 0x10).permitted is True


def test_deny_forbids_both_despite_existing_window():
    policy = _policy(_rule("r0", base=0x0, size=0x1000,
                           permission=AccessPermission.DENY))
    read = policy.may_read("cpu0", "mem0", 0x10, route_exists=True)
    assert read.window_matched is True      # the window DOES match
    assert read.permitted is False          # ...and permission still forbids
    assert read.permission is AccessPermission.DENY


def test_window_is_half_open():
    policy = _policy(_rule("r0", base=0x1000, size=0x1000))
    assert policy.may_read("cpu0", "mem0", 0x1000).window_matched is True
    assert policy.may_read("cpu0", "mem0", 0x1FFF).window_matched is True
    assert policy.may_read("cpu0", "mem0", 0x2000).window_matched is False


def test_query_in_other_address_space_does_not_match():
    policy = _policy(_rule("r0", base=0x0, size=0x1000,
                           space=AddressSpace.GLOBAL))
    assert policy.may_read("cpu0", "mem0", 0x10,
                           address_space=AddressSpace.LOCAL) \
        .window_matched is False


def test_address_space_must_be_typed():
    with pytest.raises(AccessPolicyError, match="AddressSpace"):
        _policy(_rule()).may_read("cpu0", "mem0", 0x0,
                                  address_space="GLOBAL")


# ------------------------------------------- scenario G: two distinct facts --

def test_network_reachable_and_access_forbidden_are_separate_facts():
    """route+window OK, permission DENY -> reachable AND forbidden."""
    policy = _policy(_rule("r0", base=0x0, size=0x1000,
                           permission=AccessPermission.DENY))
    d = policy.may_read("cpu0", "mem0", 0x10,
                        endpoint_exists=True, route_exists=True)
    assert d.endpoint_exists is True
    assert d.route_exists is True
    assert d.network_reachable is True      # fact A: the network gets there
    assert d.access_forbidden is True       # fact B: the policy says no
    assert d.permitted is False
    assert d.rule_id == "r0"


def test_reachable_none_when_a_rung_was_never_evaluated():
    policy = _policy(_rule("r0", base=0x0, size=0x1000))
    d = policy.may_read("cpu0", "mem0", 0x10)   # route not evaluated here
    assert d.route_exists is None
    assert d.network_reachable is None          # NOT False
    assert d.access_forbidden is False


def test_unreachable_even_when_permission_grants():
    policy = _policy(_rule("r0", base=0x0, size=0x1000))
    d = policy.may_write("cpu0", "mem0", 0x10,
                         endpoint_exists=True, route_exists=False)
    assert d.network_reachable is False
    assert d.access_forbidden is False


def test_route_unknown_plus_window_matched_is_unknown_not_false():
    policy = _policy(_rule("r0", base=0x0, size=0x1000))
    d = policy.may_read("cpu0", "mem0", 0x10)
    assert d.window_matched is True
    assert d.route_exists is None
    assert d.network_reachable is None


def test_unevaluated_rungs_stay_none_through_serialization():
    d = AccessDecision(
        endpoint_exists=None, route_exists=None, window_matched=None,
        permission=None, observed=None, rule_id=None,
        reason="nothing evaluated", permitted=None)
    back = AccessDecision.from_dict(d.to_dict())
    assert back.endpoint_exists is None
    assert back.route_exists is None
    assert back.window_matched is None
    assert back.observed is None
    assert back.permitted is None
    assert back.permission is None
    # no coercion to 0 / False / ""
    assert d.to_dict() == {"endpoint_exists": None, "route_exists": None,
                           "window_matched": None, "permission": None,
                           "observed": None, "rule_id": None,
                           "reason": "nothing evaluated", "permitted": None}


def test_decision_refuses_non_bool_rung_values():
    with pytest.raises(AccessPolicyError, match="bool or None"):
        AccessDecision(endpoint_exists=1, route_exists=None,
                       window_matched=None, permission=None, observed=None,
                       rule_id=None, reason="x")
    with pytest.raises(AccessPolicyError, match="bool or None"):
        AccessDecision(endpoint_exists=None, route_exists=None,
                       window_matched=None, permission=None, observed=0,
                       rule_id=None, reason="x")


def test_decision_refuses_empty_reason():
    with pytest.raises(AccessPolicyError, match="non-empty string"):
        AccessDecision(endpoint_exists=None, route_exists=None,
                       window_matched=None, permission=None, observed=None,
                       rule_id=None, reason="")


def test_access_forbidden_is_none_when_not_evaluated():
    d = AccessDecision(endpoint_exists=None, route_exists=None,
                       window_matched=None, permission=None, observed=None,
                       rule_id=None, reason="unknown", permitted=None)
    assert d.access_forbidden is None


# ---------------------------------------------------------- derivation ------

def test_identity_is_stable_under_declaration_order_of_identical_set():
    a = _policy(_rule("r0", base=0x0, size=0x1000),
                _rule("r1", base=0x1000, size=0x1000))
    with pytest.raises(AccessPolicyError, match="canonical order"):
        _policy(_rule("r1", base=0x1000, size=0x1000),
                _rule("r0", base=0x0, size=0x1000))


def test_hash_covers_rules_and_unmatched_policy():
    base = _policy(_rule("r0", base=0x0, size=0x1000))
    other_perm = _policy(_rule("r0", base=0x0, size=0x1000,
                               permission=AccessPermission.RO))
    other_unmatched = _policy(_rule("r0", base=0x0, size=0x1000),
                              unmatched=UnmatchedAccessPolicy.ALLOW)
    hashes = {base.policy_hash, other_perm.policy_hash,
              other_unmatched.policy_hash}
    assert len(hashes) == 3
