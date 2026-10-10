"""Bounded synchronous product adapter; diagnostic abstract evidence, not jobs.

No request generation, paths, native backend selection or qualification. The
runner is event-driven (no elapsed-cycle horizon); demand/geometry bounds cap
work instead. Noncompletion is a typed refusal, never a partial success.
"""
import json

from veritx_dse.application.errors import ControlPlaneError, ErrorCode, intent_error
from veritx_dse.application.data_movement import PROFILE, execute_data_movement
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.errors import Refusal, SemanticError, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.physical_placement import PhysicalPlacement
from veritx_dse.workload.data_movement import DataMovementWorkload

MAX_BODY_BYTES = 262144
LIMITS = {'body_bytes': MAX_BODY_BYTES, 'operations': 64, 'routers': 64,
          'endpoints': 64, 'payload_and_control_bytes': 65536,
          'children': 4096, 'flits': 65536}
COUPLED_PROFILE = 'COUPLED_TENSOR_REFERENCE_V1'
COUPLED_LIMITS = {'body_bytes': MAX_BODY_BYTES, 'routers': 64,
                  'endpoints': 64, 'nodes': 256, 'accesses': 64,
                  'requests': 4096, 'flits': 65536}


def _run_coupled_revision_experiment(project_id, revision_id, revision, doc):
    from veritx_dse.application.coupled_tensor import execute_coupled_tensor
    from veritx_dse.application.tensor_demand import RemoteDemandPolicy
    from veritx_dse.model.coupled_tensor import CoupledTensorWorkload

    if not isinstance(doc, dict) or set(doc) != {'profile', 'workload', 'transport', 'placement'}:
        raise intent_error('connected tensor experiment requires exactly profile, workload, transport and placement')
    if len(json.dumps(doc, allow_nan=False).encode()) > MAX_BODY_BYTES:
        raise UnsupportedSemantics('synchronous experiment body exceeds 256 KiB')
    if doc['profile'] != COUPLED_PROFILE:
        raise UnsupportedSemantics('only explicit COUPLED_TENSOR_REFERENCE_V1 is supported; native coupled execution is unavailable')
    raw = revision.get('request')
    if not isinstance(raw, dict) or raw.get('schema_version') != 5:
        raise UnsupportedSemantics('connected tensor experiment requires a V5 immutable revision')
    request = CompileRequestV5.from_dict(raw)
    if revision.get('design_hash') != 'sha256:' + request.design_hash():
        raise EvidenceInvalid('stored revision root identity differs from its request')
    if revision.get('compilation', {}).get('status') != 'COMPILED':
        raise UnsupportedSemantics('experiment requires a successfully compiled immutable revision')
    topology = revision.get('topology') or {}
    if (not topology.get('routers') or len(topology['routers']) > COUPLED_LIMITS['routers']
            or sum(a.count for a in request.base_v4.agents) > COUPLED_LIMITS['endpoints']
            or len(json.dumps(raw).encode()) > MAX_BODY_BYTES):
        raise UnsupportedSemantics('synchronous tensor experiment requires <=64 routers/endpoints and <=256 KiB immutable root')
    workload = CoupledTensorWorkload.from_dict(doc['workload'])
    policy = RemoteDemandPolicy.from_dict(doc['transport'])
    placement = PhysicalPlacement.from_dict(doc['placement'])
    if workload.demand.design_hash != request.design_hash():
        raise EvidenceInvalid('tensor demand does not bind the immutable V5 revision')
    if len(workload.nodes) > COUPLED_LIMITS['nodes'] or len(workload.demand.accesses) > COUPLED_LIMITS['accesses']:
        raise UnsupportedSemantics('synchronous tensor experiment exceeds node/access bounds')
    compilation = FabricCompiler().compile(request)
    if compilation.status != 'COMPILED':
        raise UnsupportedSemantics('immutable revision recompile refused: ' + str(compilation.error))
    root = compilation.compiled_system
    placement.validate_against(root.resource_graph)
    if len(root.resource_graph.routers) > COUPLED_LIMITS['routers']:
        raise UnsupportedSemantics('synchronous tensor experiment exceeds 64 actual routers')
    from veritx_dse.workload.tensor_demand import lower_tensor_demand
    demand = lower_tensor_demand(compilation, workload.demand, allow_owner_cache=True)
    if len(demand.requests) > COUPLED_LIMITS['requests']:
        raise UnsupportedSemantics('synchronous tensor experiment exceeds 4096 lowered requests')
    width = compilation.bundle.packet_format.payload_bits_per_flit
    flits = 0
    for row in demand.requests:
        payload_flits = (8 * (row.payload_bytes + policy.control_bytes) + width - 1) // width
        flits += 2 * payload_flits
    if flits > COUPLED_LIMITS['flits']:
        raise UnsupportedSemantics('synchronous tensor experiment exceeds 65536 request/response flits')
    evidence = execute_coupled_tensor(compilation, workload, policy, placement).to_dict()
    return {'status': 'DIAGNOSTIC_REFERENCE', 'profile': COUPLED_PROFILE,
            'binding': {'project_id': project_id, 'revision_id': revision_id,
                        'design_hash': request.design_hash(), 'system_hash': root.system_hash(),
                        'workload_id': workload.workload_id(), 'placement_id': placement.artifact_id()},
            'limits': COUPLED_LIMITS, 'qualification': False,
            'support': {'reference_execution': 'SUPPORTED',
                        'native_execution': 'UNSUPPORTED_NO_CONNECTED_NATIVE_DRIVER',
                        'calibrated': False, 'qualified': False},
            'evidence': evidence}


def run_revision_experiment(project_id, revision_id, revision, doc):
    try:
        if isinstance(doc, dict) and doc.get('profile') == COUPLED_PROFILE:
            return _run_coupled_revision_experiment(project_id, revision_id, revision, doc)
        if isinstance(doc, dict) and doc.get('profile') == 'NATIVE_COUPLED_TENSOR_DIAGNOSTIC_V1':
            raise UnsupportedSemantics('native coupled tensor execution is unavailable; low-level adapters are not a connected driver')
        if not isinstance(doc, dict) or set(doc) != {'profile', 'workload', 'placement'}:
            raise intent_error('explicit experiment requires exactly profile, workload and placement')
        if len(json.dumps(doc, allow_nan=False).encode()) > MAX_BODY_BYTES:
            raise UnsupportedSemantics('synchronous experiment body exceeds 256 KiB')
        if doc['profile'] != PROFILE:
            raise UnsupportedSemantics('only explicit ABSTRACT_DATA_MOVEMENT_V1 is supported')
        raw = revision['request']
        if raw.get('schema_version') != 5:
            raise UnsupportedSemantics('explicit abstract experiments require a V5 revision')
        request = CompileRequestV5.from_dict(raw)
        if revision.get('design_hash') != 'sha256:' + request.design_hash():
            raise EvidenceInvalid('stored revision root identity differs from its request')
        if revision.get('compilation', {}).get('status') != 'COMPILED':
            raise UnsupportedSemantics('experiment requires a successfully compiled immutable revision')
        # Bound before recompile using the immutable, previously materialized revision.
        topology = revision.get('topology') or {}
        if (not topology.get('routers') or len(topology['routers']) > LIMITS['routers']
                or sum(a.count for a in request.base_v4.agents) > LIMITS['endpoints']
                or len(json.dumps(raw).encode()) > MAX_BODY_BYTES):
            raise UnsupportedSemantics('synchronous experiment requires <=64 routers/endpoints and <=256 KiB root')
        operations = doc['workload'].get('operations') if isinstance(doc['workload'], dict) else None
        if not isinstance(operations, list) or not 1 <= len(operations) <= LIMITS['operations']:
            raise UnsupportedSemantics('synchronous experiment requires 1..64 explicit operations')
        routers = doc['placement'].get('routers') if isinstance(doc['placement'], dict) else None
        if not isinstance(routers, list) or len(routers) > LIMITS['routers']:
            raise UnsupportedSemantics('synchronous experiment placement exceeds 64 routers')
        workload = DataMovementWorkload.from_dict(doc['workload'])
        placement = PhysicalPlacement.from_dict(doc['placement'])
        if workload.design_hash != request.design_hash():
            raise EvidenceInvalid('workload does not bind the immutable V5 revision')
        if sum(o.payload_bytes + o.control_bytes for o in workload.operations) > LIMITS['payload_and_control_bytes']:
            raise UnsupportedSemantics('synchronous experiment exceeds 65536 payload/control bytes')
        compilation = FabricCompiler().compile(request)
        if compilation.status != 'COMPILED':
            raise UnsupportedSemantics('immutable revision recompile refused: ' + str(compilation.error))
        root = compilation.compiled_system
        placement.validate_against(root.resource_graph)
        if len(root.resource_graph.routers) > LIMITS['routers']:
            raise UnsupportedSemantics('synchronous experiment exceeds 64 actual routers')
        policies = {r['endpoint_id']: r['transaction_policy'] for r in root.execution_contract.endpoints} if root.execution_contract else {}
        children = flits = 0
        width = compilation.bundle.packet_format.payload_bits_per_flit
        for op in workload.operations:
            policy = policies.get(op.initiator)
            splitting = policy.get('splitting') if policy else None
            boundary = splitting['boundary_bytes'] if splitting else op.payload_bytes
            count = (op.payload_bytes + boundary - 1) // boundary
            children += count
            # Conservative upper bound: two messages/child plus padding.
            flits += (8 * (op.payload_bytes + count * op.control_bytes) + width - 1) // width + 2 * count
        if children > LIMITS['children'] or flits > LIMITS['flits']:
            raise UnsupportedSemantics('synchronous experiment exceeds 4096 children or 65536 flits')
        evidence = execute_data_movement(compilation, workload, placement).to_dict()
        return {'status': 'DIAGNOSTIC_ABSTRACT', 'profile': PROFILE,
                'binding': {'project_id': project_id, 'revision_id': revision_id,
                            'design_hash': request.design_hash(), 'system_hash': root.system_hash(),
                            'workload_id': workload.workload_id(), 'placement_id': placement.artifact_id()},
                'limits': LIMITS, 'qualification': False, 'evidence': evidence}
    except ControlPlaneError:
        raise
    except (Refusal, SemanticError, ValueError) as exc:
        code = (ErrorCode.EVIDENCE_INVALID if isinstance(exc, EvidenceInvalid) else
                ErrorCode.UNSUPPORTED_SEMANTICS if isinstance(exc, UnsupportedSemantics) else
                ErrorCode.INVALID_INTENT)
        raise ControlPlaneError(code, str(exc), operation='abstract_experiment', resource_id=revision_id) from exc
