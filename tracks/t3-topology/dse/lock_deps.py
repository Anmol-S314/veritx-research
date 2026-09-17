#!/usr/bin/env python3
"""Regenerate dse/requirements.lock (make lock).

Kept as a script because a multi-line inline python recipe in a Makefile
is a tab/space trap — the previous inline version broke every other make
target with "missing separator" (PR A follow-up, 2026-09-17).
"""
import importlib.metadata as im

pkgs = ["pydantic", "numpy", "scipy", "scikit-optimize", "pyyaml"]
print("# veritx runtime dependency lock — verified-PRD Integrity PR A (§11.3)")
print("#")
print("# This file is the scientific-environment identity for runs: its SHA256 is")
print('# recorded in provenance.json ("python_dependency_lock"). Regenerate it with')
print("#   make -C tracks/t3-topology lock")
print("# after changing pyproject [project].dependencies, and commit the result.")
print("#")
print("# Exact pins captured on the reference environment (Python 3.14.4, linux);")
print("# they satisfy the >= floors declared in pyproject.toml.")
for p in pkgs:
    print(f"{p}=={im.version(p)}")
