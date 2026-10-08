"""CompileRequestV5 at the compiler seam (P6).

V5 carries intent V4 cannot express. The compiler must never silently drop
it: a design that sets no extension is the sole lossless down-projection to
V4 and compiles exactly as V4 did, and a design that sets one gets a typed
refusal that names the field AND the compiler stage that owns it — never a
bare "V5 unsupported".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.model.access_policy import AccessPolicyArtifact  # noqa: E402
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.model.compile_request_v5 import (  # noqa: E402
    AgentIntentV5,
    CompileRequestV5,
    migrate_v4_to_v5,
)
from veritx_dse.model.ip_catalog import InterfaceRole  # noqa: E402
from veritx_dse.model.domain_intent import (  # noqa: E402
    ClockSource,
    ClockSourceKind,
    ClockDomain,
    PowerDomain,
    PowerPolicy,
)
from veritx_dse.model.sideband import (  # noqa: E402
    Direction,
    SidebandInterface,
    SidebandKind,
)


def _v4() -> CompileRequestV4:
    path = DSE.parent / "examples" / "qwen3_moe_tp2_ep4_16tiles-v4.json"
    return CompileRequestV4.from_dict(json.loads(path.read_text()))


def test_neutral_v5_down_projects_and_compiles():
    neutral = migrate_v4_to_v5(_v4())
    compilation = FabricCompiler().compile(neutral)
    assert compilation.status == "COMPILED", compilation.error
    # The down-projection is lossless, so it compiles the V4 it wraps.
    assert compilation.request is neutral.base_v4


def test_v5_extension_refusal_names_the_field_and_its_stage():
    extended = CompileRequestV5(
        base_v4=_v4(),
        agent_intents=(AgentIntentV5(
            agent_group_index=0,
            interface_role=InterfaceRole.INITIATOR),))
    compilation = FabricCompiler().compile(extended)
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "ATTACHMENT"
    assert "agent_intents" in compilation.error
    assert "owner stage ATTACHMENT" in compilation.error


def test_access_policy_is_materialized_and_emitted():
    """The one V5 field with a standalone artifact is emitted, not refused."""
    policy = AccessPolicyArtifact(rules=())
    extended = CompileRequestV5(base_v4=_v4(), access_policy=policy)
    compilation = FabricCompiler().compile(extended)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.access_policy is policy


def test_sidebands_are_materialized_and_emitted():
    extended = CompileRequestV5(
        base_v4=_v4(),
        sideband_interfaces=(SidebandInterface(
            id="sb0", kind=SidebandKind.INTERRUPT,
            direction=Direction.OUTPUT, width_bits=1),))
    compilation = FabricCompiler().compile(extended)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.sideband_set is not None
    assert compilation.sideband_set.content_hash
    assert [i.id for i in compilation.sideband_set.interfaces] == ["sb0"]


def test_clock_domains_are_materialized_and_emitted():
    extended = CompileRequestV5(
        base_v4=_v4(),
        clock_sources=(ClockSource(id="clk0", kind=ClockSourceKind.PLL,
                                   frequency_hz=1_000_000_000),),
        clock_domains=(ClockDomain(id="core", source_id="clk0",
                                   frequency_hz=500_000_000,
                                   divider_num=2, divider_den=1),))
    compilation = FabricCompiler().compile(extended)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.clock_domains is not None
    assert compilation.clock_domains.content_hash
    assert [d.id for d in compilation.clock_domains.domains] == ["core"]


def test_v5_refusal_names_every_extension_not_just_the_first():
    extended = CompileRequestV5(
        base_v4=_v4(),
        agent_intents=(AgentIntentV5(
            agent_group_index=0,
            interface_role=InterfaceRole.INITIATOR),),
        power_domains=(PowerDomain(id="pd0",
                                   policy=PowerPolicy.ALWAYS_ON),))
    compilation = FabricCompiler().compile(extended)
    assert compilation.status == "UNSUPPORTED"
    # The earliest owning stage is reported, but both fields are named.
    assert compilation.stopped_at_stage == "ATTACHMENT"
    assert "agent_intents" in compilation.error
    assert "power_domains" in compilation.error
    assert "owner stage COMPOSE" in compilation.error
    assert "never dropped" in compilation.error
