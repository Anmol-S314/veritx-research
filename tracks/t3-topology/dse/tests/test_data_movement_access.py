"""Full-range access enforcement before transaction issue."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_data_movement_execution import experiment
from veritx_dse.application.data_movement import (
    execute_data_movement, AccessDenied, DataMovementEvidence,
)
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.artifact import FrozenMap
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid
from veritx_dse.model.access_policy import (
    AccessPolicyArtifact, AccessRule, AccessPermission, AddressSpace,
    UnmatchedAccessPolicy, AccessPolicyError,
)
from veritx_dse.model.transaction_intent import OutstandingTracker, OrderingPolicy, OrderingMode
from fractions import Fraction
from veritx_dse.workload.data_movement import DataMovementOperation


def rule(name, base, size, permission=AccessPermission.RW, space=AddressSpace.GLOBAL):
    return AccessRule(name, "group:0", "group:1", base, size, permission, space)


def authorized(policy=None, space=AddressSpace.GLOBAL):
    c, w, p = experiment()
    policy = policy if policy is not None else AccessPolicyArtifact((
        rule("write", 0x1000, 512, AccessPermission.WO),
        rule("read", 0x2000, 512, AccessPermission.RO),))
    request = replace(c.request, access_policy=policy)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    return compiled, replace(w, design_hash=request.design_hash(),
                            operations=tuple(replace(op, address_space=space) for op in w.operations)), p


def test_allowed_operations_conserve_and_record_bound_authorization():
    c, w, p = authorized()
    result = execute_data_movement(c, w, p)
    doc = result.to_dict()
    assert doc["summary"]["payload_bytes"] == 1024
    assert doc["summary"]["children_completed"] == 8
    assert doc["scope"]["access_authorization"] == "ABSTRACT_POLICY_ENFORCED_NOT_FIREWALL"
    assert {a["operation_id"] for a in doc["authorizations"]} == {"write", "read"}
    for authorization in doc["authorizations"]:
        assert authorization["policy_hash"] == c.access_policy.policy_hash
        for span in authorization["spans"]:
            decision = span["decision"]
            assert decision["permitted"] is True and decision["observed"] is True
            assert decision["endpoint_exists"] is True and decision["route_exists"] is True
    assert DataMovementEvidence.from_dict(json.loads(json.dumps(doc)), compilation=c, workload=w, placement=p) == result


def test_interior_denial_refuses_every_child_before_issue(monkeypatch):
    policy = AccessPolicyArtifact((rule("left", 0x1000, 47),
        rule("blocked-byte", 0x102f, 1, AccessPermission.DENY),
        rule("right", 0x1030, 512-48), rule("read", 0x2000, 512)))
    c, w, p = authorized(policy)
    def unexpected_issue(*_args, **_kwargs):
        pytest.fail("a denied workload must refuse before any issue")
    monkeypatch.setattr(OutstandingTracker, "try_issue", unexpected_issue)
    with pytest.raises(AccessDenied) as caught:
        execute_data_movement(c, w, p)
    evidence = caught.value.authorization
    assert evidence["issued_children"] == 0
    assert evidence["spans"][0]["decision"]["permitted"] is True
    assert evidence["spans"][-1]["decision"]["permitted"] is True
    denied = evidence["spans"][1]
    assert (denied["address_start"], denied["address_end"]) == (0x102f, 0x1030)
    assert denied["decision"]["rule_id"] == "blocked-byte"
    assert denied["decision"]["route_exists"] is True
    assert denied["decision"]["observed"] is False


@pytest.mark.parametrize("permission", [AccessPermission.RO, AccessPermission.DENY])
def test_write_permission_denial_is_distinct_from_routability(permission):
    c, w, p = authorized(AccessPolicyArtifact((rule("window", 0x1000, 0x2000, permission),)))
    with pytest.raises(AccessDenied) as caught:
        execute_data_movement(c, w, p)
    decision = caught.value.authorization["spans"][0]["decision"]
    assert decision["route_exists"] is True and decision["permitted"] is False


def test_gap_denies_by_default_but_explicit_unmatched_allow_is_respected():
    rows = (rule("partial", 0x1000, 256), rule("read", 0x2000, 512))
    with pytest.raises(AccessDenied) as caught:
        execute_data_movement(*authorized(AccessPolicyArtifact(rows)))
    assert caught.value.authorization["spans"][-1]["decision"]["window_matched"] is False
    doc = execute_data_movement(*authorized(AccessPolicyArtifact(rows, unmatched_policy=UnmatchedAccessPolicy.ALLOW))).to_dict()
    gap = doc["authorizations"][0]["spans"][-1]["decision"]
    assert gap["window_matched"] is False and gap["permission"] is None
    assert gap["permitted"] is True and gap["observed"] is True


def test_adjacent_grants_cover_a_transaction_without_one_oversized_rule():
    policy = AccessPolicyArtifact((rule("a", 0x1000, 256), rule("b", 0x1100, 256), rule("c", 0x2000, 512)))
    doc = execute_data_movement(*authorized(policy)).to_dict()
    spans = doc["authorizations"][0]["spans"]
    assert [(s["address_start"], s["address_end"]) for s in spans] == [(0x1000, 0x1100), (0x1100, 0x1200)]


def test_explicit_address_space_required_and_global_never_grants_local():
    policy = AccessPolicyArtifact((rule("global", 0x1000, 0x2000),))
    with pytest.raises(InvalidInput, match="address_space"):
        execute_data_movement(*authorized(policy, space=None))
    with pytest.raises(AccessDenied):
        execute_data_movement(*authorized(policy, space=AddressSpace.LOCAL))
    local = AccessPolicyArtifact((rule("local", 0x1000, 0x2000, space=AddressSpace.LOCAL),))
    assert execute_data_movement(*authorized(local, space=AddressSpace.LOCAL)).data["summary"]["parents_completed"] == 2


def test_denial_of_a_later_operation_still_aborts_before_any_issue(monkeypatch):
    c, w, p = authorized(AccessPolicyArtifact((rule("write-only", 0x1000, 512),)))
    monkeypatch.setattr(OutstandingTracker, "try_issue", lambda *_: pytest.fail("preflight must be atomic"))
    with pytest.raises(AccessDenied) as caught:
        execute_data_movement(c, w, p)
    assert caught.value.authorization["operation_id"] == "read"


def test_wrong_initiator_group_does_not_inherit_another_agents_grant():
    c, w, p = authorized(AccessPolicyArtifact((replace(rule("wrong", 0x1000, 0x2000), initiator="group:2"),)))
    with pytest.raises(AccessDenied) as caught:
        execute_data_movement(c, w, p)
    assert caught.value.authorization["spans"][0]["decision"]["window_matched"] is False


def test_hazard_ordering_keeps_local_and_global_addresses_separate():
    c, w, p = authorized(AccessPolicyArtifact((
        rule("a-local", 0x1000, 512, space=AddressSpace.LOCAL),
        rule("b-global", 0x1000, 512, space=AddressSpace.GLOBAL))))
    intent = c.request.agent_intents[0]
    intent = replace(intent, transaction_policy=replace(intent.transaction_policy,
        ordering=OrderingPolicy(OrderingMode.CUSTOM, enforce_raw=True)))
    req = replace(c.request, agent_intents=(intent, *c.request.agent_intents[1:]))
    c = FabricCompiler().compile(req)
    w = replace(w, design_hash=req.design_hash(), operations=(
        replace(w.operations[0], address_space=AddressSpace.LOCAL),
        replace(w.operations[1], address=0x1000, address_space=AddressSpace.GLOBAL)))
    rows = execute_data_movement(c, w, p).to_dict()["children"]
    def timestamp(row, key):
        return Fraction(row[key]["numerator"], row[key]["denominator"])
    assert min(timestamp(r, "issued_s") for r in rows if r["kind"] == "READ") < max(
        timestamp(r, "completed_s") for r in rows if r["kind"] == "WRITE")


def test_authorization_tamper_cannot_be_resealed_as_valid_evidence():
    c, w, p = authorized()
    result = execute_data_movement(c, w, p)
    doc = result.to_dict()
    doc.pop("artifact_id")
    doc["authorizations"][0]["spans"][0]["decision"]["permission"] = "DENY"
    with pytest.raises(EvidenceInvalid):
        DataMovementEvidence(FrozenMap(doc)).revalidate(c, w, p)


def test_operation_space_roundtrips_without_changing_old_operation_bytes():
    _, w, _ = experiment()
    old = w.operations[0]
    assert "address_space" not in old.to_dict()
    assert "response_traffic_class" not in old.to_dict()
    assert DataMovementOperation.from_dict(old.to_dict()) == old
    declared = replace(old, address_space=AddressSpace.LOCAL,
                       response_traffic_class="memory_response")
    assert DataMovementOperation.from_dict(declared.to_dict()) == declared
    for invalid in (None, True, "", "PRIVATE"):
        with pytest.raises(InvalidInput):
            DataMovementOperation.from_dict({**old.to_dict(), "address_space": invalid})


def test_range_decisions_match_independent_byte_permissions():
    policy = AccessPolicyArtifact((rule("ro", 2, 3, AccessPermission.RO),
        rule("deny", 8, 1, AccessPermission.DENY), rule("rw", 9, 4)))
    for operation in ("read", "write"):
        for start in range(16):
            for size in range(1, 17-start):
                spans = policy.range_decisions(operation=operation, initiator="group:0", target="group:1",
                    address=start, byte_length=size, address_space=AddressSpace.GLOBAL)
                actual = [d.permitted for a, b, d in spans for _ in range(a, b)]
                expected = [((2 <= a < 5 and operation == "read") or 9 <= a < 13)
                            for a in range(start, start+size)]
                assert actual == expected
                assert spans[0][0] == start and spans[-1][1] == start+size


@pytest.mark.parametrize("start,size", [(True, 1), (0, False), (0, 0), (-1, 1), (2**64-1, 2)])
def test_invalid_range_refuses(start, size):
    with pytest.raises(AccessPolicyError):
        AccessPolicyArtifact(()).range_decisions(operation="read", initiator="a", target="b",
            address=start, byte_length=size, address_space=AddressSpace.GLOBAL)


def test_authorized_example_runs_through_cli():
    example = Path(__file__).resolve().parents[1] / "examples/addressed_memory_access_v5.json"
    process = subprocess.run([sys.executable, "-m", "veritx_dse.cli.cli", "--json", "evaluate",
                              "data-movement", "--experiment", str(example)],
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    doc = json.loads(process.stdout)
    assert doc["summary"]["parents_completed"] == 2
    assert [a["spans"][0]["decision"]["permission"] for a in doc["authorizations"]] == ["WO", "RO"]


def test_cli_denial_reports_zero_issue_and_reachable_but_forbidden(tmp_path):
    c, w, p = authorized(AccessPolicyArtifact(()))
    doc = {"design": c.request.to_dict(), "workload": w.to_dict(), "placement": p.to_dict()}
    source = tmp_path / "denied.json"
    source.write_text(json.dumps(doc))
    process = subprocess.run([sys.executable, "-m", "veritx_dse.application.data_movement", str(source)],
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 1, process.stderr
    refusal = json.loads(process.stdout)
    assert refusal["code"] == "ACCESS_DENIED"
    assert refusal["authorization"]["issued_children"] == 0
    assert refusal["authorization"]["spans"][0]["decision"]["route_exists"] is True
    assert "Traceback" not in process.stderr
