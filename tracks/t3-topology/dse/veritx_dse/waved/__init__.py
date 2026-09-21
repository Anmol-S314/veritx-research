"""veritx_dse.waved — Wave D: distributed semantics (WHAT communication occurs).

Wave D layers an exact, content-addressed semantics chain on top of the
sealed Wave-B authorities:

    WaveDWorkload (new)              — declared operations    [D1]
    ParallelismArtifact (new)        — rank-space geometry    [D1]
    WaveDWorkloadSemantics (new)     — semantic envelope      [D1]
    OperationGraph (new)             — causal op DAG          [D2]
    LogicalMessageArtifact (new)     — scheduled messages     [D3]
    PhysicalTrafficArtifact (new)    — packets + flits        [D4]
    ConservationLedger (derived)     — per-class laws         [D4]

Every artifact is transitively immutable and strictly parseable via
the one artifact primitive (``veritx_dse.core.artifact``) and persisted as a first-class resource
through ``veritx_dse.application.waved_resources`` — the only
scientific trust path for loading one back.

Wave D owns WHAT; Wave B/C own execution and evidence; Wave E owns WHEN.
Nothing here duplicates a Wave-B authority: rank space is
``model.placement``, mapping is ``model.mapping`` + ``model.resolved_fabric``,
packet format is ``model.packet_format``, VC semantics are
``model.vc_assignment``.
"""

WAVED_SCHEMA_VERSION = 1
