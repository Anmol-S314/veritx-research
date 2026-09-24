"""Projection closure (P0.8): required fields present, no undeclared field.

Every pinned profile value must render verbatim, every required field must
be present, and no simulation-relevant key outside the audited surface may
appear.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim_projection import _parents  # noqa: E402

from veritx_dse.backend import booksim_projection as bp  # noqa: E402


def _prepared():
    _compiled, parents = _parents()
    return bp.prepare_booksim_input(parents)


def test_every_required_field_is_rendered_and_none_undeclared():
    prepared = _prepared()
    rendered = bp.parse_config_values(prepared.config_text)
    profile = bp.select_booksim_profile(_parents()[1])
    assert profile.rendered_names() <= set(rendered)
    assert set(rendered) <= profile.known_names()


def test_undeclared_rendered_field_refuses(monkeypatch):
    _compiled, parents = _parents()
    real = bp.render_config

    def tampered(*args, **kwargs):
        return real(*args, **kwargs) + b"\nevil_knob = 1\n"

    monkeypatch.setattr(bp, "render_config", tampered)
    with pytest.raises(bp.BookSimProjectionError,
                       match="outside the audited"):
        bp.prepare_booksim_input(parents)


def test_missing_required_field_refuses(monkeypatch):
    _compiled, parents = _parents()
    real = bp.render_config

    def drop_num_vcs(*args, **kwargs):
        text = real(*args, **kwargs).decode()
        kept = [line for line in text.splitlines()
                if not line.strip().startswith("num_vcs")]
        return ("\n".join(kept) + "\n").encode()

    monkeypatch.setattr(bp, "render_config", drop_num_vcs)
    with pytest.raises(bp.BookSimProjectionError, match="missing required"):
        bp.prepare_booksim_input(parents)
