"""The explicit backend registry.

Registration means only: VERITX knows an adapter implementation.
Availability and readiness are determined by assessment at plan/evaluate
time — never by installation. No plugin framework, no discovery: the
default registry is a literal tuple of adapters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from veritx_dse.backend.adapter import BackendAdapter


class BackendRegistryError(ValueError):
    """The registry was misused (duplicate identity, unknown backend)."""


class BackendRegistry:
    """A frozen-by-construction set of adapters keyed by backend_id."""

    def __init__(self, adapters: tuple[BackendAdapter, ...] = ()):
        seen: dict[str, BackendAdapter] = {}
        for adapter in adapters:
            backend_id = adapter.backend_id
            if backend_id in seen:
                raise BackendRegistryError(
                    f"duplicate backend_id {backend_id!r} in registry")
            seen[backend_id] = adapter
        self._adapters = seen

    def register(self, adapter: BackendAdapter) -> None:
        backend_id = adapter.backend_id
        if backend_id in self._adapters:
            raise BackendRegistryError(
                f"backend_id {backend_id!r} is already registered")
        self._adapters[backend_id] = adapter

    def get(self, backend_id: str) -> BackendAdapter | None:
        return self._adapters.get(backend_id)

    def require(self, backend_id: str) -> BackendAdapter:
        adapter = self._adapters.get(backend_id)
        if adapter is None:
            raise BackendRegistryError(
                f"no backend registered as {backend_id!r}")
        return adapter

    def adapters(self) -> tuple[BackendAdapter, ...]:
        """Registration order is the iteration order; the PLANNER owns
        deterministic selection and must never depend on it."""
        return tuple(self._adapters.values())

    def __iter__(self) -> Iterator[BackendAdapter]:
        return iter(self.adapters())

    def __contains__(self, backend_id: object) -> bool:
        return backend_id in self._adapters

    def __len__(self) -> int:
        return len(self._adapters)


def default_backend_registry(
    *,
    booksim_bin: str | Path | None = None,
    astra_bin: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> BackendRegistry:
    """The certified federation, explicitly enumerated.

    Registration is installation, not readiness: each adapter's
    assessment decides whether it can actually execute on this tree.
    Runtime configuration (explicit binaries, repo root) is bound here,
    once — never reconstructed ad hoc in service methods.
    """
    from veritx_dse.backend.astra_adapter import Astra2Adapter
    from veritx_dse.backend.booksim_adapter import BookSimAdapter
    root = Path(repo_root) if repo_root is not None else None
    return BackendRegistry((
        BookSimAdapter(
            binary=(Path(booksim_bin)
                    if booksim_bin is not None else None),
            repo_root=root),
        Astra2Adapter(
            binary=(Path(astra_bin)
                    if astra_bin is not None else None),
            repo_root=root),
    ))


__all__ = [
    "BackendRegistry", "BackendRegistryError", "default_backend_registry",
]
