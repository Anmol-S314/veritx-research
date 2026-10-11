"""Explicit, bounded pins for the diagnostic native multicast producer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veritx_dse.core.artifact import FrozenMap, ImmutableError, canonical_bytes, content_id, thaw
from veritx_dse.core.errors import InvalidInput
from veritx_dse.model.resource_graph import exact_int

PROFILE = "NATIVE_MULTICAST_SOURCE_ROUTER_DIAGNOSTIC_V1"
PIN_NAMES = frozenset({
    "booksim_executable", "booksim_source_manifest", "booksim_build_provenance",
})


def _validate_pin(pin, name):
    if (not isinstance(pin, (dict, FrozenMap)) or set(pin) != {"path", "sha256"}
            or not isinstance(pin["path"], str)
            or not Path(pin["path"]).is_absolute()
            or not isinstance(pin["sha256"], str)
            or len(pin["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in pin["sha256"])):
        raise InvalidInput(f"{name} requires an absolute path and lowercase SHA-256 pin")


@dataclass(frozen=True)
class NativeMulticastConfig:
    files: FrozenMap
    host_flit_limit: int
    max_engine_steps: int

    def __post_init__(self):
        if not isinstance(self.files, FrozenMap) or set(self.files) != PIN_NAMES:
            raise InvalidInput("native multicast config requires all three producer pins")
        for name, pin in self.files.items():
            _validate_pin(pin, name)
        exact_int("host_flit_limit", self.host_flit_limit, 1)
        exact_int("max_engine_steps", self.max_engine_steps, 1)
        if self.host_flit_limit > 65536 or self.max_engine_steps > 1_000_000:
            raise InvalidInput("native multicast resource bound exceeded")

    def to_dict(self):
        return {"files": thaw(self.files), "host_flit_limit": self.host_flit_limit,
                "max_engine_steps": self.max_engine_steps}

    def config_id(self):
        return content_id("veritx/NativeMulticastConfig/v1", self.to_dict())

    @classmethod
    def from_dict(cls, doc):
        if not isinstance(doc, dict) or set(doc) != {
                "files", "host_flit_limit", "max_engine_steps"}:
            raise InvalidInput("native multicast config has unknown or missing fields")
        if not isinstance(doc["files"], dict):
            raise InvalidInput("native multicast files must be an object")
        try:
            return cls(FrozenMap(doc["files"]), doc["host_flit_limit"],
                       doc["max_engine_steps"])
        except ImmutableError as exc:
            raise InvalidInput("native multicast config contains noncanonical values") from exc


__all__ = ["PROFILE", "PIN_NAMES", "NativeMulticastConfig"]
