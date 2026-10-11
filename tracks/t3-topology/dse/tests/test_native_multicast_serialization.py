"""Serialization is not native execution qualification."""
import json

from veritx_dse.backend.native_multicast import NativeMulticastRequest


def test_native_multicast_request_exact_json_roundtrip():
    request = NativeMulticastRequest(
        'op', 'workload', 0, (1, 2), 64, 0, 'data', 0, 3, (4, 5),
        'topology', 'mapping', 'attachment', 'binding')
    expected = {
        'operation_id': 'op', 'workload_id': 'workload', 'source_rank': 0,
        'destination_ranks': [1, 2], 'payload_bytes': 64,
        'replication_point_rank': 0, 'traffic_class': 'data',
        'traffic_class_id': 0, 'source_router': 3,
        'destination_routers': [4, 5], 'topology_hash': 'topology',
        'mapping_hash': 'mapping', 'attachment_hash': 'attachment',
        'class_binding_hash': 'binding',
    }
    doc = json.loads(json.dumps(request.to_dict()))
    assert doc == expected
    restored = NativeMulticastRequest(**{
        **doc, 'destination_ranks': tuple(doc['destination_ranks']),
        'destination_routers': tuple(doc['destination_routers']),
    })
    assert restored == request
    assert restored.to_dict() == expected
