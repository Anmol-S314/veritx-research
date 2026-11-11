"""Parameterized, compiled-graph Chipyard source export for all fourteen families.

This is an explicit source-routed preview, not a replacement routing policy:
all paths come from recorded compiler decisions. No shortest-path fallback,
workload resizing, shared-tap expansion, or hardware tool execution occurs.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path
import zipfile

from veritx_dse.product.chipyard_sources import EXPORTERS

TARGET_IDS = frozenset(key for key, _ in EXPORTERS)
MAX_PATHS = 131072
MAX_TOTAL_HOPS = 1_000_000
MAX_CHOICES_PER_PAIR = 1024


def topology_id_for_bundle(bundle) -> str:
    intent = bundle.design.topology
    kind = getattr(intent, 'kind', None)
    mapping = {'mesh': 'mesh8x8', 'torus': 'torus8x8', 'concentrated_mesh': 'cmesh',
               'ring_native': 'ring', 'fly_native': 'fly64', 'qtree_native': 'qtree',
               'tree4_native': 'tree4', 'flatfly': 'flatfly', 'srota': 'srota8x8',
               'fattree': 'fattree', 'dragonfly': 'dragonflynew', 'kncube': 'kncube'}
    if kind == 'gec':
        mode = getattr(getattr(intent, 'mode', None), 'value', None)
        key = {'multidrop': 'gec_mecs', 'hybrid': 'gec_hybrid'}.get(mode)
    elif kind == 'structured':
        key = {'dragonfly': 'dragonflynew', 'dragonflynew': 'dragonflynew',
               'kncube': 'kncube'}.get(getattr(intent, 'family', None))
    else:
        key = mapping.get(kind)
    if key not in TARGET_IDS:
        raise FabricSourceError('The compiled family has no all-topology source identity')
    return key


LIMITATIONS = [
    'Source-routed SINGLE-flit preview, not a simulation-equivalent compiled router.',
    'Each injection explicitly chooses one recorded route/VC alternative; native congestion selectors, FIU, telemetry and side buffers are not implemented by this preview.',
    'Ready/valid flow control, per-router VC queues and round-robin arbitration differ from the compiled credit/iSLIP pipeline.',
    'VC masks retain all recorded legal alternatives; the preview retains the current VC when allowed and otherwise selects the lowest legal VC, not a native VC allocator.',
    'No multi-flit packet reservations, endpoint protocol adaptation, ordering, CDC, physical timing or electrical shared-wire qualification.',
]


class FabricSourceError(ValueError):
    pass


def contract_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def contract_from_bundle(bundle, *, topology_id: str, revision_id: str) -> dict:
    """Read an existing in-memory compiled bundle; never invoke the compiler."""
    if topology_id not in TARGET_IDS or topology_id != topology_id_for_bundle(bundle):
        raise FabricSourceError('Topology ID does not match the compiled family')
    top, route = bundle.topology, bundle.router_route
    routers = sorted(r.router_id for r in top.routers)
    dense = {native: i for i, native in enumerate(routers)}
    endpoints = sorted(bundle.attachment.endpoints, key=lambda e: e.endpoint_id)
    if [e.endpoint_id for e in endpoints] != list(range(len(endpoints))):
        raise FabricSourceError('Endpoint IDs must be contiguous')
    resources, private = [], {}
    for channel in top.channels:
        private[channel.channel_id] = len(resources)
        resources.append({'native_id': channel.channel_id, 'kind': 'CHANNEL',
                          'src': dense[channel.src_router], 'taps': [dense[channel.dst_router]],
                          'width_bits': channel.width_bits, 'latency_cycles': channel.latency_cycles})
    for wire in top.shared_links:
        resources.append({'native_id': wire.shared_link_id, 'kind': 'SHARED_LINK',
                          'src': dense[wire.src_router], 'taps': [dense[t] for t in wire.taps],
                          'width_bits': wire.width_bits, 'latency_cycles': wire.latency_cycles})
    vcs = bundle.vc_assignment.vc_count
    egress = dict(bundle.resolved_route.routing_pairs())
    classes = dict(bundle.vc_assignment.vc_to_routing_class)
    terminal_map = getattr(route, 'terminal_to_router', {})
    def terminal(endpoint):
        if terminal_map:
            candidates = [t for t, r in terminal_map.items() if r == egress[endpoint.endpoint_id]]
            # Preserve concentration port identity, not just the egress router.
            port = endpoint.egress_port_id if endpoint.egress_port_id is not None else endpoint.port_id
            if not 0 <= port < len(candidates):
                raise FabricSourceError('Cannot bind endpoint to a unique routing terminal')
            return sorted(candidates)[port]
        return egress[endpoint.endpoint_id]

    def steps(cur, dst_router, dst_terminal, cls, shape):
        if hasattr(route, 'entries'):
            channel_id = route.entries.get((cls, cur, dst_router))
            if channel_id is None or channel_id not in private:
                raise FabricSourceError(f'Missing compiled channel route {cls}/{cur}/{dst_router}')
            index = private[channel_id]
            allowed = [vc for vc, owner in classes.items() if owner == cls]
            if not allowed:
                raise FabricSourceError('Routing class has no concrete VC')
            return [(index, resources[index]['taps'][0], allowed, shape)]
        if hasattr(route, 'choices'):
            options = route.choices.get((cur, dst_terminal), ())
        elif hasattr(route, 'decisions'):
            decision = route.decisions.get((cur, dst_terminal))
            options = () if decision is None else (decision,)
        else:
            raise FabricSourceError('Compiled routing representation has no explicit decisions; refusing a guessed route')
        result = []
        for decision in options:
            partition = decision.vc_partition
            option_shape = getattr(route, 'shape_of_partition', {}).get(partition)
            if shape is not None and option_shape is not None and shape != option_shape:
                continue
            if decision.resource.kind.value == 'SHARED_LINK':
                matches = [(i, r) for i, r in enumerate(resources)
                           if r['kind'] == 'SHARED_LINK' and r['src'] == dense[cur]
                           and decision.tap is not None and 0 <= decision.tap < len(r['taps'])
                           and r['taps'][decision.tap] == dense[decision.next_router]]
            else:
                matches = [(i, r) for i, r in enumerate(resources)
                           if r['kind'] == 'CHANNEL' and r['src'] == dense[cur]
                           and r['taps'] == [dense[decision.next_router]]]
            if len(matches) != 1:
                raise FabricSourceError('Compiled route resource is ambiguous or absent in the physical graph')
            allowed = route.partition_to_vcs.get(partition, ())
            if not allowed or any(not 0 <= vc < vcs for vc in allowed):
                raise FabricSourceError('Route VC lies outside the compiled VC assignment')
            result.append((matches[0][0], dense[decision.next_router], list(allowed), option_shape or shape))
        if not result:
            raise FabricSourceError('No legal route choices remain for a compiled state')
        return result

    paths, choices = [], []
    total_hops = 0
    route_classes = sorted(set(classes.values())) if hasattr(route, 'entries') else [route.routing_class]
    for src in endpoints:
        for dst in endpoints:
            pair = []
            for cls in route_classes:
                stack = [(src.router_id, None, [], frozenset())]
                while stack:
                    cur, shape, hops, visited = stack.pop()
                    if cur == egress[dst.endpoint_id]:
                        total_hops += len(hops)
                        if total_hops > MAX_TOTAL_HOPS:
                            raise FabricSourceError('Exact path inventory exceeds the total-hop source limit')
                        pair.append(len(paths))
                        paths.append({'source': src.endpoint_id, 'destination': dst.endpoint_id,
                                      'routing_class': cls, 'hops': hops})
                        if len(pair) > MAX_CHOICES_PER_PAIR or len(paths) > MAX_PATHS:
                            raise FabricSourceError('Exact route alternatives exceed the source limit; no alternatives were silently dropped')
                        continue
                    state = (cur, shape)
                    if state in visited:
                        raise FabricSourceError('Compiled route alternatives contain a loop; refusing path expansion')
                    options = steps(cur, egress[dst.endpoint_id], terminal(dst), cls, shape)
                    for resource, next_dense, allowed_vcs, next_shape in reversed(options):
                        stack.append((routers[next_dense], next_shape,
                                      hops + [[resource, next_dense, allowed_vcs]], visited | {state}))
            if not pair:
                raise FabricSourceError('A compiled endpoint pair has no route')
            choices.append(pair)
    doc = {
        'schema': 'veritx/compiled-fabric-source/1', 'topology_id': topology_id,
        'revision_id': revision_id, 'design_hash': bundle.design.design_hash(),
        'router_ids': routers, 'resources': resources,
        'ingress_routers': [dense[e.router_id] for e in endpoints],
        'egress_routers': [dense[egress[e.endpoint_id]] for e in endpoints],
        'packet_format': bundle.packet_format.to_dict(),
        'vc_assignment': bundle.vc_assignment.to_dict(),
        'router_behavior': bundle.router_behavior.to_dict(),
        'source_topology': top.to_dict(),
        'source_route': route.to_dict() if hasattr(route, 'to_dict') else route.canonical_dict(),
        'paths': paths, 'choices': choices, 'limitations': LIMITATIONS,
        'final_implementation': False, 'generation': 'NOT_RUN', 'simulation': 'NOT_RUN',
    }
    validate_contract(doc)
    return doc


def validate_contract(doc: dict) -> None:
    if doc.get('schema') != 'veritx/compiled-fabric-source/1' or doc.get('topology_id') not in TARGET_IDS:
        raise FabricSourceError('Invalid compiled-fabric schema or topology ID')
    routers, resources = doc['router_ids'], doc['resources']
    count = len(routers)
    if (not 1 <= count <= 1024 or len(set(routers)) != count
            or any(type(r) is not int or r < 0 for r in routers)):
        raise FabricSourceError('Router inventory must contain 1–1024 distinct nonnegative IDs')
    ingress, egress = doc['ingress_routers'], doc['egress_routers']
    n = len(ingress)
    if not 1 <= n <= 256 or len(egress) != n:
        raise FabricSourceError('Ingress/egress endpoint maps must agree')
    if any(type(r) is not int or not 0 <= r < count for r in ingress + egress):
        raise FabricSourceError('Endpoint references a missing router')
    packet = doc['packet_format']
    width = packet['flit_width_bits']
    vcs = doc['vc_assignment']['vc_count']
    if not 1 <= vcs <= 64 or not 8 <= width <= 1024:
        raise FabricSourceError('Invalid VC count or flit width')
    depth = doc['router_behavior']['input_buffer_depth_flits_per_vc']
    if type(depth) is not int or not 1 <= depth <= 256:
        raise FabricSourceError('Preview queue depth must be 1–256')
    fields = {f['name']: f for f in packet['fields']}
    if len(fields) != len(packet['fields']):
        raise FabricSourceError('Packet field names must be unique')
    occupied = set()
    for field in fields.values():
        if field['lsb'] < 0 or field['width'] <= 0 or field['lsb'] + field['width'] > width:
            raise FabricSourceError('Packet field lies outside the flit')
        bits = set(range(field['lsb'], field['lsb'] + field['width']))
        if occupied & bits:
            raise FabricSourceError('Packet fields overlap')
        occupied.update(bits)
    for name in ('destination_endpoint', 'vc_id', 'flit_type'):
        f = fields.get(name)
        if f is None or f['width'] <= 0 or f['lsb'] < 0 or f['lsb'] + f['width'] > width:
            raise FabricSourceError(f'Invalid packet field: {name}')
    if (2**fields['vc_id']['width'] < vcs or 2**fields['destination_endpoint']['width'] < n
            or fields['flit_type']['width'] < 2):
        raise FabricSourceError('Packet fields cannot encode the endpoint/VC/SINGLE-flit inventory')
    identities = [(r['kind'], r['native_id']) for r in resources]
    if len(set(identities)) != len(identities):
        raise FabricSourceError('Physical resource identities must be unique within their namespace')
    for r in resources:
        if r['kind'] not in ('CHANNEL', 'SHARED_LINK') or not r['taps'] or len(set(r['taps'])) != len(r['taps']):
            raise FabricSourceError('Invalid physical resource')
        if r['kind'] == 'CHANNEL' and len(r['taps']) != 1:
            raise FabricSourceError('A point-to-point channel cannot contain multiple taps')
        if any(type(v) is not int or not 0 <= v < count for v in [r['src']] + r['taps']):
            raise FabricSourceError('Resource references a missing router')
        if r['width_bits'] != width or not 1 <= r['latency_cycles'] <= 64:
            raise FabricSourceError('Resource width must equal the flit width and latency must be positive')
    paths, choices = doc['paths'], doc['choices']
    if (not 1 <= len(paths) <= MAX_PATHS or len(choices) != n*n
            or sum(len(path['hops']) for path in paths) > MAX_TOTAL_HOPS):
        raise FabricSourceError('Invalid or excessive route-alternative inventory')
    for src in range(n):
        for dst in range(n):
            options = choices[src*n+dst]
            if not options or len(options) > MAX_CHOICES_PER_PAIR:
                raise FabricSourceError('Missing or excessive endpoint route alternatives')
            for path_id in options:
                if type(path_id) is not int or not 0 <= path_id < len(paths):
                    raise FabricSourceError('Route choice references a missing path')
                p = paths[path_id]
                if (p['source'], p['destination']) != (src, dst):
                    raise FabricSourceError('A route choice belongs to another endpoint pair')
                current, seen = ingress[src], set()
                if len(p['hops']) > count:
                    raise FabricSourceError('Recorded path exceeds the router inventory')
                for resource, nxt, allowed_vcs in p['hops']:
                    if current in seen or not 0 <= resource < len(resources):
                        raise FabricSourceError('Loop or invalid resource in recorded path')
                    seen.add(current)
                    r = resources[resource]
                    if (r['src'] != current or nxt not in r['taps'] or not allowed_vcs
                            or any(type(vc) is not int or not 0 <= vc < vcs for vc in allowed_vcs)):
                        raise FabricSourceError('Recorded hop violates physical resource or VC identity')
                    current = nxt
                if current != egress[dst]:
                    raise FabricSourceError('Recorded path does not reach the endpoint egress')


def binary_contract(doc: dict) -> bytes:
    """Data resource, not a giant JVM static initializer."""
    validate_contract(doc)
    values = [0x56545831, len(doc['router_ids']), doc['packet_format']['flit_width_bits'],
              doc['vc_assignment']['vc_count'], doc['router_behavior']['input_buffer_depth_flits_per_vc']]
    fields = {f['name']: f for f in doc['packet_format']['fields']}
    for name in ('destination_endpoint', 'vc_id', 'flit_type'):
        values.extend((fields[name]['lsb'], fields[name]['width']))
    def vector(items):
        values.append(len(items))
        values.extend(items)
    vector(doc['ingress_routers'])
    vector(doc['egress_routers'])
    values.append(len(doc['resources']))
    for resource in doc['resources']:
        values.extend((resource['src'], resource['latency_cycles']))
        vector(resource['taps'])
    values.append(len(doc['paths']))
    for path in doc['paths']:
        values.append(len(path['hops']))
        for resource, nxt, allowed in path['hops']:
            values.extend((resource, nxt))
            vector(allowed)
    values.append(len(doc['choices']))
    for options in doc['choices']:
        vector(options)
    return struct.pack('>' + 'i'*len(values), *values)


def render_config(doc: dict) -> str:
    data_hash = hashlib.sha256(binary_contract(doc)).hexdigest()
    return ('package veritx.chipyard\nobject SelectedFabric {\n'
            f'  val contractHash = "{contract_hash(doc)}"\n'
            f'  val params = FabricContract.load("/selected-fabric.bin", "{data_hash}")\n'
            '}\n')


def source_bundle(doc: dict, repo_root: Path) -> bytes:
    """Return parameterized source, not generated Verilog; no subprocesses."""
    config = render_config(doc)
    core = repo_root / 'tracks/t3-topology/rtl/chipyard/CompiledFabricPreview.scala'
    data = core.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('contract.json', json.dumps(doc, indent=2) + '\n')
        archive.writestr('scala/SelectedFabric.scala', config)
        archive.writestr('scala/CompiledFabricPreview.scala', data)
        archive.writestr('resources/selected-fabric.bin', binary_contract(doc))
        archive.writestr('README.md',
            '# Revision-bound Chipyard fabric source\n\n'
            'Source only. No toolchain was run to create this archive.\n'
            'Use scala/ as the existing Chipyard constellation source directory and resources/ as its resource directory.\n'
            'Keep SelectedFabric.scala and selected-fabric.bin together: their hash binding is checked before elaboration.\n'
            'Only run the existing capped private runner after explicit permission to compile.\n\n'
            'Ingress contains flit plus routeChoice. For source s and destination d, contract.json choices[s*N+d] '
            'lists path IDs; routeChoice is the index in that list, not the global path ID. '
            'Pack the flit using the exact recorded packet fields and SINGLE type 3. '
            'The core preserves payload and rewrites only the hop-local VC field.\n\n'
            + '\n'.join('- ' + item for item in LIMITATIONS) + '\n')
        archive.writestr('source-manifest.json', json.dumps({
            'scope': 'PARAMETERIZED_COMPILED_FABRIC_SOURCE', 'topology_id': doc['topology_id'],
            'revision_id': doc['revision_id'], 'design_hash': doc['design_hash'],
            'contract_hash': contract_hash(doc), 'final_implementation': False,
            'generation': 'NOT_RUN', 'lint': 'NOT_RUN', 'simulation': 'NOT_RUN',
            'limitations': LIMITATIONS,
            'files': {'scala/SelectedFabric.scala': hashlib.sha256(config.encode()).hexdigest(),
                      'scala/CompiledFabricPreview.scala': hashlib.sha256(data).hexdigest(),
                      'resources/selected-fabric.bin': hashlib.sha256(binary_contract(doc)).hexdigest()},
        }, indent=2) + '\n')
    return output.getvalue()


if __name__ == '__main__':
    import argparse
    from veritx_dse.core.paths import REPO
    parser = argparse.ArgumentParser(description='Package an existing fabric contract as Chipyard source; never compile it')
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.contract.read_text())
    archive = source_bundle(document, REPO)
    # Do not overwrite another operator's archive or a symlink.
    with args.out.open('xb') as destination:
        destination.write(archive)
