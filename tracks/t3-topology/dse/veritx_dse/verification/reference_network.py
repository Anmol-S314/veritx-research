"""Executable standalone reference network envelopes (diagnostic, unqualified).

python -m veritx_dse.verification.reference_network --input FILE --output FILE
Optional --verify-evidence FILE strictly replays all supplied parents/inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.packet_format import PacketFormatArtifact
from veritx_dse.model.vc_resource import VCResourceArtifact
from veritx_dse.model.reference_network import ReferenceNetworkError, exact, keys, sealed
from veritx_dse.model.rcu_reference import (
    PROFILE as RCU_PROFILE, RCUReferenceContract, execute_rcu,
)
from veritx_dse.model.multicast_tree import (
    PROFILE as MULTICAST_PROFILE, MulticastTreeContract, execute_multicast,
)


def execute_request(request):
    if type(request) is not dict:
        raise ReferenceNetworkError("request must be an object")
    profile = request.get("profile")
    if profile == RCU_PROFILE:
        keys(request, {"profile", "topology", "attachment", "contract", "events", "until_cycle"}, "RCU request")
    elif profile == MULTICAST_PROFILE:
        keys(request, {"profile", "topology", "attachment", "vc_resource", "packet_format", "contract"}, "multicast request")
    else:
        raise ReferenceNetworkError("unknown reference profile")
    topology = TopologyArtifact.from_dict(request["topology"])
    attachment = AgentAttachmentArtifact.from_dict(request["attachment"])
    exact(request["topology"], topology.to_dict(), "topology serialization")
    exact(request["attachment"], attachment.to_dict(), "attachment serialization")
    if profile == RCU_PROFILE:
        contract = RCUReferenceContract.from_dict(request["contract"], topology=topology, attachment=attachment)
        result = execute_rcu(contract, request["events"], request["until_cycle"])
    else:
        vc_resource = VCResourceArtifact.from_dict(request["vc_resource"])
        packet_format = PacketFormatArtifact.from_dict(request["packet_format"])
        exact(request["vc_resource"], vc_resource.to_dict(), "VC serialization")
        exact(request["packet_format"], packet_format.to_dict(), "packet format serialization")
        contract = MulticastTreeContract.from_dict(request["contract"], topology=topology, attachment=attachment,
                                                   vc_resource=vc_resource, packet_format=packet_format)
        result = execute_multicast(contract)
    return sealed("ReferenceNetworkExecution/v1", {"request": request, "result": result,
                  "provenance": "DIRTY_TREE_DIAGNOSTIC_NO_QUALIFICATION"})


def validate_execution(evidence, *, request):
    exact(evidence, execute_request(request), "reference request replay")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceNetworkError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def load_json(path):
    def invalid_constant(value):
        raise ReferenceNetworkError(f"nonfinite JSON constant {value}")
    return json.loads(Path(path).read_text(), object_pairs_hook=_object, parse_constant=invalid_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--verify-evidence")
    args = parser.parse_args(argv)
    request = load_json(args.input)
    result = execute_request(request)
    if args.verify_evidence:
        validate_execution(load_json(args.verify_evidence), request=request)
    Path(args.output).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
