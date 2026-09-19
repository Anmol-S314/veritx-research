"""veritx_dse — AI-Noc Design Space Exploration toolkit.

This package re-exports all public APIs for backward compatibility.
New code should import from subpackages directly:
    from veritx_dse.model import CompileRequest
    from veritx_dse.simulation import run_booksim
"""
__version__ = "0.3.0"

# Re-export core
from .core.constants import *
from .core.config import config
from .core.errors import VeritXError, ConfigError, TraceError, BookSimError
from .core.logging import Ctx, log, ok, fail, verbose, banner, output, get_logger, setup_file_logging
from .core.recovery import temporary_directory, atomic_write
from .core.paths import REPO, DSE_DIR, RUNS_DIR

# Re-export model
from .model.compile_model import (
    CompileRequest, Workload, Agent, DependencyGraph, NocConfig,
    ModelFamily, ServingMode, AgentKind, TopologyFamily,
    QoSClass, Requirement, Dependency, DepKind,
    verify_design, derive_vc_assignment, derive_vc_assignment_artifact,
    migrate_design,
    AddressMap, AddressRange, PhysicalContext,
)
from .model.presets import SWEEP_TOPOS, WORKLOAD_PRESETS, lookup_topo
from .model.placement import (
    ParallelismShape, AgentInstance, LogicalRank, NodeInventory,
    build_inventory, rank_of, coords_of,
)
from .model.mapping import (
    MappingArtifact, RankPlacement, MappingError, derive_mapping,
)
from .model.topology_artifact import (
    TopologyArtifact, Router, DirectedChannel, PhysicalLink,
    MaterializedFamily, TopologyError, materialize_topology, materialize_family,
)
from .model.attachment import (
    AgentAttachmentArtifact, Endpoint, AttachmentError, derive_attachment,
)
from .model.resolved_route import (
    ResolvedRouteArtifact, ResolvedRouteError, LOCAL_EJECTION,
    derive_resolved_route,
)
from .model.vc_assignment import (
    VCAssignmentArtifact, VCAssignmentError, make_vc_assignment_artifact,
)
from .model.packet_format import (
    DEFAULT_MAX_PACKET_FLITS,
    FLIT_TYPE_ENCODING, HEADER_REPLICATION_EVERY_FLIT,
    PACKETIZATION_BOUNDED_WORMHOLE,
    FieldMutability, FieldRole, PacketField,
    PacketFormatArtifact, PacketFormatError,
    derive_packet_format, encoding_width, network_packet_count,
)
from .model.router_behavior import (
    AllocatorPolicy, BufferOrganization, FlowControlProtocol,
    InputVCPacketPolicy, RouterBehaviorArtifact, RouterBehaviorError,
    VCAllocationScope, VCReusePolicy, canonical_allocator,
    derive_router_behavior,
)

# Re-export simulation
from .simulation.booksim import build_config, run_booksim, find_booksim_bin, detect_trace_stats
from .simulation.traces import validate_trace, extract_uniform

# Re-export reports
from .reports.reports import generate_report, _scale_factor, estimate_fabric_area, estimate_total_power
from .reports.artifact import sign_manifest, verify_manifest, DesignManifest

# Re-export verification
from .verification.uvm_gen import generate_uvm
from .verification.channel_vc_cdg import (
    ChannelVCCDG, DeadlockCertificate, CDGError,
    CHANNEL_VC_DEPENDENCY_ACYCLIC, DEADLOCK_PROOF_METHODS,
    build_channel_vc_cdg, certify_channel_vc_deadlock,
)

# Backward compatibility - re-export submodules as attributes
from .core import constants, logging, recovery, paths
from .model import compile_model, presets
from .simulation import booksim, traces, trace_to_binary
from .reports import reports, artifact
from .verification import uvm_gen
