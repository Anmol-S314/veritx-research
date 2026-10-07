# Canonical Intent Contract — shared vocabulary for the V5 intent submodels

**Status:** binding design contract for every new intent submodel authored in this pass.
**Audience:** implementation agents. Read this before writing a line of code.
**Why it exists:** five agents are authoring disjoint modules that must later compose
into ONE `CompileRequestV5`. Divergent vocabulary is an architectural fork
(see program §73). This file is the single vocabulary.

Governing rules from the program:
- evidence-first; the server is the authority; React never decides capability
- unknown keys **refuse**; invalid values **refuse**; no silent fallbacks
- missing != 0, unsupported != disabled, derived != measured, external != certified
- no binary floating point for identity-bearing clock values
- `PARTIAL`/`BLOCKED`/`UNSUPPORTED`/`NOT_IMPLEMENTED` are truthful states; only `READY`
  when the capability ladder actually closes

---

## 1. Module shape (mandatory for every new intent module)

Mirror `model/srota_intent.py`, `model/address_decode.py`, `model/router_behavior.py`.

```python
"""veritx_dse.model.<name> — <one-line purpose>.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compile_model import _as_int, _as_str   # reuse, do not re-invent
```

Required elements:

1. `SCHEMA_VERSION: int = 1` — the artifact's own schema version.
2. `<Name>Error(ValueError, SemanticError)` — the typed refusal for this module.
   Never raise a bare `ValueError` for a semantic refusal.
3. `_strict_keys(d, allowed: frozenset, where: str)` — refuse unknown fields by name.
   Reuse the local private helper pattern from `address_decode.py:64`.
4. Frozen `@dataclass` types with `__post_init__` validation.
5. `to_dict() -> dict[str, Any]` and `@classmethod from_dict(d) -> <type>`.
   `from_dict` must **roundtrip**: `T.from_dict(x.to_dict()) == x`.
6. `canonical_dict()` **only** where identity enters a hash, and then only when
   declaration order that is not science is sorted (see `noc_controls.canonical_dict`).
   Non-scientific ordering must not change identity; scientific values keep their value.

Do **not**:
- do not put simulation semantics in this layer (no BookSim knobs, no `k`, no `c`)
- do not import React/TS-facing names or write UI enums here
- do not invent area, power, WNS, PPA, clock rates, or "recommended" mechanisms
- do not add fields "because the UI has a control for it"

## 2. Refusal style

```python
raise SomeError(
    "crossing 'x' requests SYNC_2FF for a MULTI_BIT signal: a multi-bit bus "
    "cannot cross on a single 2FF synchronizer. Declare ASYNC_FIFO or "
    "HANDSHAKE, or set mechanism=UNRESOLVED with a reason.")
```

Every refusal message must (a) name the offending object, (b) name the violated
law, (c) say what the legal alternatives are. A refusal is never a downgrade to
a different mechanism.

**Never auto-select a mechanism.** If information is insufficient the correct
value is `UNRESOLVED` with an explicit reason — never an assumed `SYNC_2FF`.

## 3. Enum vocabulary — use these EXACT names

Each module owns exactly one concern. Do not define a concept a sibling module
already owns; import it instead, or ask the integrator.

### `transaction_intent.py`
```
OrderingMode       = STRONG | RELAXED | CUSTOM
```

### `access_policy.py`
```
AccessPermission   = RW | RO | WO | DENY
AddressSpace       = GLOBAL | LOCAL
```

### `domain_intent.py`
```
ClockSourceKind    = PLL | XTAL | EXTERNAL | DIVIDER
Polarity           = ACTIVE_HIGH | ACTIVE_LOW
AssertionMode      = ASYNC | SYNC
DeassertionMode    = SYNC            # ASYNC deassert is a typed REFUSAL (§6)
PowerPolicy        = ALWAYS_ON | COLLAPSIBLE
SignalKind         = SINGLE_BIT | MULTI_BIT | PULSE | BUS
CrossingMechanism  = SYNC_2FF | SYNC_3FF | HANDSHAKE | ASYNC_FIFO | UNRESOLVED
PointerEncoding    = BINARY | GRAY
CrossingVerdict    = INTENT_VALID | UNRESOLVED_CROSSING
FidelityLevel      = HETERO_TIMING_ABSTRACT | NOT_MODELED
```

### `sideband.py`
```
SidebandKind       = INTERRUPT | QOS | ERROR | POISON | SNOOP_CONTROL |
                     POWER_STATE | RESET | CLOCK_REQUEST | CREDIT_STATUS |
                     TRACE | CUSTOM
Direction          = OUTPUT | INPUT
```

### `ip_catalog.py`
```
IpCategory         = COMPUTE | MEMORY | NETWORK | BRIDGE | SUPPORT
```

---

## 4. Transaction intent — exact semantics

**Critical distinction, restated in every docstring that touches it:**

```
workload operation -> transaction -> agent issue policy -> packetization
  -> flits -> VC/router flow control -> BookSim
```

`max_outstanding` is an **AGENT TRANSACTION CREDIT**, a bound on live
transactions at one agent. It is **NOT** a BookSim router buffer credit, which
is a per-VC flit slot. Do not name, alias, thread, or convert between them.

### `OutstandingLimit`
| field | type | law |
|---|---|---|
| `reads` | `int \| None` | if present: `>= 1` |
| `writes` | `int \| None` | if present: `>= 1` |
| `total` | `int \| None` | if present: `>= 1` and `>= reads` (if set), `>= writes` (if set) |

At least one of the three must be present, else the limit is vacuous → refuse.
`None` means **not constrained by design intent**, which is exactly what v4
behaved like. It is never `0`.

### `OrderingPolicy`
| field | type | law |
|---|---|---|
| `mode` | `OrderingMode` | required |
| `enforce_raw` | `bool` | |
| `enforce_war` | `bool` | |
| `enforce_waw` | `bool` | |
| `ordering_domain` | `str \| None` | non-empty if present |

- `STRONG` ⇒ `enforce_raw and enforce_war and enforce_waw` must all be `True`.
  Any `False` ⇒ refuse ("STRONG means no later operation in the ordering domain
  issues before an earlier one completes; a disabled hazard makes it not strong").
- `CUSTOM` ⇒ at least one hazard `True`, else refuse (vacuous).
- `RELAXED` ⇒ any combination, including all `False` (independent progress).

Do **not** call this "AXI ordering". Protocol translation is a later adapter;
these are canonical, protocol-neutral semantics.

### `SplittingPolicy`
| field | type | law |
|---|---|---|
| `max_payload_bytes` | `int` | `>= 1` |
| `boundary_bytes` | `int` | `>= 1`, **power of two**, and `max_payload_bytes % boundary_bytes == 0` |

Legal values are therefore powers of two that evenly divide the max payload
(e.g. 64 B, 128 B under a 512 B payload). A "custom" value that is not a power
of two, or that does not divide the payload, **refuses**.

### `ReorderingPolicy`
| field | type | law |
|---|---|---|
| `enabled` | `bool` | |
| `max_window` | `int` | `>= 0`; `enabled=True` ⇒ `>= 1`; `enabled=False` ⇒ must be `0` (else the two fields disagree → refuse) |

### Splitting must materialize children
```python
split_transactions(*, parent_id, address_base, payload_bytes,
                   splitting, ordering_domain, traffic_class) -> tuple[ChildTransaction, ...]
```
`ChildTransaction`: `sequence` (0-based), `address_start`, `address_end`
(**exclusive**), `byte_length`, `parent_id`, `ordering_domain`, `traffic_class`,
`is_last`.

Invariants (assert in tests):
- `sum(c.byte_length for c in children) == payload_bytes` (conservation)
- children are contiguous: `children[i].address_end == children[i+1].address_start`
- `children[0].address_start == address_base`
- `children[-1].address_end == address_base + payload_bytes`
- every child carries `parent_id` and `ordering_domain`

512 B @ 128 B ⇒ exactly 4 children: `0..128, 128..256, 256..384, 384..512`
(address_end exclusive; describe ranges as `[start, end)`).

### `OutstandingTracker` (proves the limit is real)
A tiny deterministic model with `try_issue(read|write) -> bool` and
`complete(read|write)`. Invariant: live counts never exceed the limit, and a
slot freed by `complete` lets a previously blocked issue through. This is a
**Q1 mathematical micro-oracle**, not a simulator — no timing, no flits.

---

## 5. Access policy — the ladder must stay separated

Five distinct facts, never merged:

```
1. endpoint exists
2. route exists
3. address window matches
4. permission allows the operation
5. the transaction was observed/executed
```

`AccessDecision` therefore carries each rung explicitly with the type
`bool | None`, where `None` means **not evaluated / unknown**, never `False`.

```python
@dataclass(frozen=True)
class AccessDecision:
    endpoint_exists: bool | None
    route_exists: bool | None        # None = route not evaluated here
    window_matched: bool | None
    permission: AccessPermission | None
    observed: bool | None
    rule_id: str | None
    reason: str
```
Provide `@property network_reachable` (= `window_matched` and `route_exists is True`
evaluated separately from permission) so the UI can render
"network reachable / access forbidden" as **two different facts** (§86 Scenario G).

`AccessRule`: `rule_id`, `initiator`, `target`, `address_base`, `address_size`,
`permission`.
Laws:
- `address_size >= 1`, `address_base >= 0`
- rules for the same `(initiator, target)` must not overlap → refuse with the
  exact colliding pair (this is the address-overlap check §14)
- `DENY` is expressed by an explicit rule, never by absence

`AccessPolicyArtifact`: `schema_version`, `rules` (canonical order: sort by
`(initiator, target, address_base, address_size, rule_id)`), `unmatched_policy`
(`DENY` | `ALLOW` — **default `DENY`**; unmapped ⇒ deny, and `unmatched_policy=ALLOW`
must be authored explicitly).

Methods: `may_read(initiator, target, address) -> AccessDecision`,
`may_write(...)`. A request for an address in no window returns
`window_matched=False`, `permission=None`, `unmatched_policy`-derived outcome —
never a fabricated permission.

Reuse `model/address_decode.py` for decode mechanics where possible; the policy
layer adds *permission* on top of *decode*. Do not fork the decode logic.

---

## 6. Clock / reset / power / crossing — exactness and honesty

### Clock
- `frequency_hz` is an **exact `int`**. Reuse the discipline of
  `tests/test_clock_parsing_exact.py`: floats like `1.5` and `0.1` are refused;
  `"1e9"` and integers above 2**53 are exact.
- `ClockSource(id, kind, frequency_hz)`; `frequency_hz >= 1`.
- `ClockDomain(id, source_id, frequency_hz, divider_num=1, divider_den=1)`.
  Law: `(source.frequency_hz * divider_den) % divider_num == 0`, and the resulting
  domain frequency is exact and `>= 1`. A non-integer division **refuses** — it is
  never rounded.
- Divider values `>= 1`.
- Unknown `source_id` in a domain ⇒ refuse (domains must reference a declared source).

### Reset
`ResetChannel(id, source_id, target_clock_domain, polarity, assertion,
deassertion, synchronizer_stages, depends_on)`.

- `deassertion == ASYNC` ⇒ **typed refusal**: "ASYNC deassertion is not
  supported: this system does not model or claim it. Use SYNC deassertion."
  This is honest, and it is a *capability fact*, not a default.
- `assertion == ASYNC` ⇒ `deassertion` must be `SYNC` (automatically true by the
  above) **and** `synchronizer_stages >= 2` is **required** — async assertion with
  no release synchronizer refuses.
- `assertion == SYNC` ⇒ `synchronizer_stages` may be `None`.
- `polarity` default `ACTIVE_HIGH`.
- **Never claim metastability proof.** Word every message as structural intent.

The canonical case, `async assert + sync deassert`, must be expressible and valid.

### Power
`PowerDomain(id, policy: PowerPolicy, declared_states: tuple[str, ...] = ())`.
Architectural intent only. Module docstring must say: *this is not UPF signoff;
no isolation, retention or level-shifter requirement is implied or generated.*

### Crossing
```python
AsyncFIFOConfig(depth, write_width, read_width, pointer_encoding,
                synchronizer_stages)
Crossing(id, src_clock, dst_clock, signal_kind, mechanism,
         synchronizer_stages=None, async_fifo=None, reason="")
```
Laws (all refuse):
- `src_clock == dst_clock` ⇒ not a crossing ⇒ refuse "same clock domain".
- `mechanism == ASYNC_FIFO` ⇔ `async_fifo is not None` (must agree both ways).
- `mechanism != ASYNC_FIFO` and `async_fifo is not None` ⇒ refuse.
- `signal_kind in (SINGLE_BIT, PULSE)` with `ASYNC_FIFO` ⇒ refuse (wrong mechanism).
- `signal_kind in (MULTI_BIT, BUS)` with `SYNC_2FF`/`SYNC_3FF` ⇒ refuse (a multi-bit
  bus cannot cross on a single-flop synchronizer).
- `mechanism == SYNC_2FF` ⇒ `synchronizer_stages == 2` (exactly).
- `mechanism == SYNC_3FF` ⇒ `synchronizer_stages == 3` (exactly).
- `mechanism in (SYNC_2FF, SYNC_3FF)` ⇒ `async_fifo is None`, and stages required.
- `mechanism == HANDSHAKE` ⇒ `async_fifo is None`, `synchronizer_stages in (None, 2, 3)`.
- `mechanism == UNRESOLVED` ⇒ `reason` non-empty; `synchronizer_stages is None`;
  `async_fifo is None`. **This is the correct answer when information is missing.**

`AsyncFIFOConfig` laws:
- `depth >= 2`
- `pointer_encoding == GRAY` ⇒ `depth` is a power of two (Gray pointer wrap law)
- `write_width >= 1`, `read_width >= 1`
- `synchronizer_stages >= 2`

### Async FIFO performance model (separate from intent correctness)
Per §33: intent correctness and performance consequence are **different objects**.
Provide `AsyncFIFOModel(config, synchronizer_latency_cycles)` with:
- `write_accepted() -> bool` (False when full ⇒ backpressure)
- `read_accepted() -> bool` (False when empty)
- `occupancy` property, `full`, `empty`
- synchronizer latency shifts a write into the readable domain after
  `synchronizer_stages` read-domain cycles

Q1 invariants to test: no over-fill beyond `depth`, no underflow below 0,
`full` at `depth`, `empty` at `0`, occupancy never negative, and ordering preserved.
**No analog/metastability modeling.**

### Fidelity labelling
Every performance claim carries `fidelity: HETERO_TIMING_ABSTRACT`. This level
retains the normal synchronous engine and models clock ratio, serialization,
CDC latency, bridge capacity, backpressure and link delay — it is explicitly
**not** true multi-rate event execution.

---

## 7. Sideband

`SidebandInterface(id, kind, direction, width_bits, clock_domain,
power_domain, protocol_binding=None)`
- `width_bits >= 1`
- `clock_domain`/`power_domain` are `str` names here; crossing resolution belongs
  to `domain_intent`, do not duplicate it.
- `protocol_binding` is a *protocol* identity (e.g. `AXI`) or `None`.

`SidebandConnection(connection_id, source, destination)` where each end is
`SidebandEndpointRef(agent, sideband_id)`.

`validate_sidebands(interfaces, connections, *, agent_universe) -> None` refuses:
- unknown `sideband_id` (existence)
- source direction must be `OUTPUT`, destination `INPUT`
- width mismatch between the two ends
- agent not in the agent universe
- a self-connection of one sideband onto itself with identical ref (no-op)

Crossing clock domains is **flagged, not solved**: expose
`requires_clock_crossing: bool` (derived from the two ends' `clock_domain`) and
link to `domain_intent` by name in the message. **Do not silently carry every
sideband over the main NoC data plane** — a sideband connection is its own edge.
Document that distinction in the module docstring.

---

## 8. IP catalog — server-owned, no invented numbers

`IpTemplate` fields (only these):
```
id, version, category, agent_kind, interface_role, protocol,
data_width_bits, address_width_bits, requires_clock_domain: bool,
requires_power_domain: bool, port_count: int, capability_requirements: tuple[str, ...],
provenance: str, area_mm2: str | None, power_w: str | None
```
- `area_mm2` and `power_w` are `None` when unknown and serialize as
  **`"NOT PROVIDED"`**. Never an estimate.
- `provenance` names a real source (e.g. `veritx_dse/model/compile_model.py:AgentKind`
  or `canonical VERITX abstraction`).
- Catalog lives in this module as `IP_CATALOG: tuple[IpTemplate, ...]` with
  `get_ip_template(id)` and `list_ip_templates(category=None)`.
  It is **server-owned**; React may only render it.
- A template whose semantics we cannot support must be present **with** a
  `capability_requirements` entry naming the gap so the Stamp action can be
  disabled with a server reason — not silently omitted.

---

## 9. Tests (every module)

File: `tests/test_<module>.py`, style copied from `tests/test_srota_intent.py`.

```python
from __future__ import annotations
import sys
from pathlib import Path
import pytest
DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
from veritx_dse.model.<module> import (...)  # noqa: E402
```

Required coverage, minimum:
1. **roundtrip** — `T.from_dict(t.to_dict()) == t` for a fully-populated example
2. **unknown key refuses** — `_strict_keys` behaviour on every `from_dict`
3. **each law refuses** — one `pytest.raises(<Module>Error)` per law in §4–§8
4. **neutral / default equivalence** — a minimal document behaves like v4 did
5. **no fabricated values** — `None` stays `None` through serialization; nothing
   coerces to `0`, `False`, or `""`
6. **conservation / watermark invariants** where §4–§6 specify one

Run before you report:
```bash
cd tracks/t3-topology/dse && PYTHONPATH="$PWD" python3 -m pytest tests/test_<module>.py -q -p no:cacheprovider
```

Report exactly what you ran and its exact result. Never say "green" without
naming the command.

---

## 10. Integration boundary (what you may NOT do)

Implementation agents own **only** their assigned module file(s) plus their own
test file. The following are integrator-only choke points — do not edit them:
```
veritx_dse/gateway/app.py
veritx_dse/application/loom_capability.py
veritx_dse/application/capability_truth.py
veritx_dse/model/compile_request_v4.py
veritx_dse/model/compile_model.py
veritx_dse/model/topology_intent.py
apps/studio/src/api/index.ts
apps/studio/src/api/types.ts
any preset / registry / migration table
```
If your module needs a change there, **return it as a note to the integrator**
instead of editing. This is what keeps one design intent, one compiler, one
capability registry (§73–§74).
