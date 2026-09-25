"""Canonical qualification registry surfaced to the Studio (C9).

The UI must never invent a qualification label. This is the single source
the gateway serves; it mirrors `docs/production/ENGINE-QUALIFICATION.md`.
"""
from __future__ import annotations

from typing import Any

QUALIFICATION: dict[str, dict[str, Any]] = {
    "booksim_embedded": {
        "role": "canonical network execution engine",
        "integration": "QUALIFIED",
        "numerical": "QUALIFIED",
        "independence": "engine under test",
        "limitations": ["route realization observed at the first hop only"],
    },
    "booksim_standalone": {
        "role": "shared-engine differential authority",
        "integration": "QUALIFIED",
        "numerical": "QUALIFIED",
        "independence": "semi-independent (same simulator, separate build)",
        "limitations": [],
    },
    "rtl": {
        "role": "independent RTL execution engine",
        "integration": "QUALIFIED",
        "numerical": "ESTABLISHED",
        "independence": "independent within the RTL domain",
        "limitations": [],
    },
    "ramulator": {
        "role": "memory engine / integration",
        "integration": "QUALIFIED",
        "numerical": "ESTABLISHED",
        "independence": "independent",
        "limitations": [],
    },
    "astra": {
        "role": "runtime / integration",
        "integration": "QUALIFIED",
        "numerical": "NOT_ESTABLISHED",
        "independence": "shares the BookSim network engine",
        "limitations": [
            "the 30M-cycle over-count was fixed (F-ASTRA-0001); aggregate now "
            "matches the declared compute+comm",
            "absolute timing remains unqualified pending independent "
            "per-domain oracles",
        ],
    },
}

WORKLOAD_LEVELS: dict[str, str] = {
    "W0": "micro-oracle (V01-V14) — RUN",
    "W1": "model-realistic — manifests owed",
    "W2": "serving-realistic — owed",
    "W3": "stress — owed",
}


def qualification_view() -> dict[str, Any]:
    return {"engines": QUALIFICATION, "workload_levels": WORKLOAD_LEVELS}
