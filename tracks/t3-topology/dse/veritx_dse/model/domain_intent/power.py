"""power — power domain policy.

Split out of veritx_dse.model.domain_intent; the package __init__
re-exports every public name, so importers are unchanged.

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._parse import _as_str, _enum, _need, _str_tuple, _strict_keys
from .enums import PowerPolicy

# --------------------------------------------------------------------------
# power
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PowerDomain:
    """Architectural power policy for one domain.

    This is NOT UPF signoff. ``policy`` labels whether the domain is
    architecturally always-on or collapsible, and ``declared_states`` names
    power states the design declares. No isolation, retention or level-shifter
    requirement is implied, and none is generated from this record.
    """

    id: str
    policy: PowerPolicy
    name: str = ""
    declared_states: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _as_str("PowerDomain.id", self.id)
        _enum("PowerDomain.policy", PowerPolicy, self.policy)
        _as_str("PowerDomain.name", self.name, allow_empty=True)
        object.__setattr__(
            self, "declared_states",
            _str_tuple("PowerDomain.declared_states",
                       tuple(self.declared_states)))

    @property
    def always_on(self) -> bool:
        return self.policy is PowerPolicy.ALWAYS_ON

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "policy": self.policy.value,
                "name": self.name,
                "declared_states": list(self.declared_states)}

    @classmethod
    def from_dict(cls, d: Any) -> "PowerDomain":
        _strict_keys(d, frozenset(
            {"id", "policy", "name", "declared_states"}), "power_domain")
        return cls(
            id=_need(d, "id", "power_domain"),
            policy=_enum("power_domain.policy", PowerPolicy,
                         _need(d, "policy", "power_domain")),
            name=d.get("name", ""),
            declared_states=tuple(d.get("declared_states", ())),
        )
