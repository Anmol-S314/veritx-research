"""Native QTree projection: exact geometry, leaf terminals and NCA equivalence."""
from veritx_dse.core.route_artifact import QTREE_NCA, QTREE_NCA_DEFINITION
from veritx_dse.model.indirect_tree import (
    materialize_qtree, qtree_nca_next, qtree_native_router_id, qtree_terminal_location,
)
from veritx_dse.model.topology_intent import QTreeIntent
from .booksim_projection import (
    BookSimProfile, ConfigRead, ParameterOwner as Owner, SemanticLoss,
    _AUDIT, _multi_class_audit, _qualify_point_to_point,
)

PROFILE_ID = "CERTIFIED_BOOKSIM_QTREE_NCA_V1"
PROFILE = BookSimProfile(
    PROFILE_ID,
    "booksim2-fork+qtree-nca-terminal-law/v1+multi-class/v1",
    _multi_class_audit(
        tuple(ConfigRead("topology", Owner.CANONICAL,
                         "networks/network.cpp", "qtree")
              if row.name == "topology" else
              ConfigRead("routing_dump_file", Owner.DERIVED,
                         "networks/network.cpp")
              if row.name == "routing_dump_file" else row
              for row in _AUDIT if row.name != "network_file")
        + (ConfigRead("k", Owner.DERIVED, "networks/qtree.cpp"),
           ConfigRead("n", Owner.DERIVED, "networks/qtree.cpp"))))


def qualify(parents, *, multi_class=False):
    topology = parents.topology
    controls = {channel.width_bits for channel in topology.channels}
    if len(controls) != 1:
        raise SemanticLoss("native QTree requires uniform channel widths")
    expected = materialize_qtree(QTreeIntent(4, 3), width_bits=next(iter(controls)))
    if topology.canonical_dict() != expected.canonical_dict():
        raise SemanticLoss("native QTree geometry/ports/seats differ from its construction")
    if len(parents.attachment.endpoints) != 64:
        raise SemanticLoss("native QTree requires the complete 64-terminal attachment")
    for endpoint in parents.attachment.endpoints:
        if (endpoint.router_id, endpoint.port_id) != qtree_terminal_location(endpoint.endpoint_id):
            raise SemanticLoss("native QTree terminal attachment differs from its leaf port law")
    if parents.route.routing_classes != (QTREE_NCA_DEFINITION,):
        raise SemanticLoss("QTree requires the sealed QTREE_NCA algorithm and parameters")
    _qualify_point_to_point(
        parents, routing_class=QTREE_NCA, multi_class=multi_class)
    if parents.vc_resource.vc_count != 1:
        raise SemanticLoss("QTree NCA v1 certifies the single-class, single-VC tree")
    channels = {channel.channel_id: channel for channel in topology.channels}
    for router in range(21):
        for terminal in range(64):
            target, _ = qtree_terminal_location(terminal)
            following, port = qtree_nca_next(topology, router, terminal)
            if target == router:
                continue
            channel = channels[parents.route.entries[(QTREE_NCA, router, target)]]
            if (channel.dst_router, channel.src_port) != (following, port):
                raise SemanticLoss("canonical route is not the native QTree NCA realization")


def observed_rows(topology):
    """The dump ABI uses dense source indices but internal next-router IDs.

    Local ejection has a null channel sink, so Network::DumpRoutingRealization
    emits the dense source index there. This translation is explicit, bound
    into prepared input identity and checked against every native dump row.
    """
    hops, ports = [], []
    for router in range(21):
        for terminal in range(64):
            following, port = qtree_nca_next(topology, router, terminal)
            native_next = (router if following == router
                           else qtree_native_router_id(topology, following))
            hops.append((router, terminal, native_next))
            ports.append((router, terminal, port))
    return tuple(hops), tuple(ports)
