"""veritx_dse.backend — authoritative backend lowering (Wave B3.7).

This package is the ONLY place where resolved Srota fabric semantics meet
concrete simulator backends. Its contract:

    every scientifically relevant backend value is either emitted from an
    authoritative semantic source or explicitly declared as a backend
    policy, approximation, irrelevance or unsupported semantic.

The package never re-derives fabric semantics and never lets a backend
become a second fabric authority:

    ResolvedFabricBundle   (validated semantic DAG, real child objects)
            │
      backend lowerer      (per BackendTarget, versioned)
            │
    BackendConfigArtifact  (path-independent projection + coverage)
            │
      run binding           (workload + exact execution inputs)
            │
    BackendInputManifest   (rendered file hashes + invocation semantics)
            │
      deterministic materialization
            │
      verify again immediately before spawn
            │
         backend process

Modules:
  contracts — BackendTarget/SemanticDimension/RepresentationStatus/
              CertificationEffect/SemanticBinding/BackendConfigArtifact/
              BackendInputManifest + strict serialization
  bundle    — ResolvedFabricBundle: the revalidated semantic DAG a lowerer
              consumes (never a root hash alone)
  booksim   — canonical BookSim lowering/materialization/certified runner
  analytical— aware/unaware analytical capability matrices
  serving   — serving-side consumer seam (no second fabric authority)
"""
from __future__ import annotations

from .contracts import (
    BackendConfigArtifact,
    BackendConfigError,
    BackendInputManifest,
    BackendInputError,
    BackendTarget,
    CertificationEffect,
    RenderedInput,
    RepresentationStatus,
    SemanticBinding,
    SemanticDimension,
)

__all__ = [
    "BackendConfigArtifact",
    "BackendConfigError",
    "BackendInputManifest",
    "BackendInputError",
    "BackendTarget",
    "CertificationEffect",
    "RenderedInput",
    "RepresentationStatus",
    "SemanticBinding",
    "SemanticDimension",
]
