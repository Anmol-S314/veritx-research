# `gateway` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py`

```text
veritx_dse.gateway — the live Studio gateway.

A thin FastAPI surface over canonical services and the product resource
layer (`veritx_dse.product`). HTTP handlers parse, validate API shape,
load resources, invoke application services, project canonical product
views and map typed failures to HTTP. NO scientific semantics live here.

The product API is versioned under ``/api/v1``. The older ad-hoc routes
(``/compile``, ``/evaluate``, ``/optimize``, ``/runs``, ``/workloads``,
``/qualification``) are retained as DEPRECATED aliases for one release;
they are not the long-term product API.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/errors.py`

```text
veritx_dse.gateway.errors — typed HTTP status mapping for the Studio API.

The gateway must never launder a programmer fault into a user error. Only
*typed semantic refusals* and *declared gateway conditions* map to 4xx/503;
anything else is a 500 and is logged. The canonical taxonomy is
``core/errors`` (``Refusal`` and subclasses) and ``application/errors``
(``ControlPlaneError``/``ErrorCode``); this module only assigns HTTP status,
it authors no semantics.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/qualification.py`

```text
Canonical qualification registry surfaced to the Studio (C9).

DEPRECATED SHIM. The single authority is now
``docs/production/ENGINE-QUALIFICATION.json`` loaded by
``veritx_dse.product.qualification``. This module no longer carries a
hand-copied duplicate of the release facts; it delegates so old importers
keep working.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/revisions.py`

```text
veritx_dse.gateway.revisions — immutable design-revision continuity.

The Studio must not resubmit raw engine JSON between stages. A compile
produces an immutable *revision*; later stages (evaluate, optimize) name the
revision and the gateway re-derives the canonical request from the stored
intent. The revision id is a content hash of the intent plus the compiled
identities, so editing a design produces a new revision and an old Run can
never be shown as the current revision.

Only the *intent* (preset/policy/overrides/name) and the compiled identities
are persisted; the canonical request and views are re-derived on read. A
compiler change that alters the identities is detected and refused rather
than silently reinterpreted.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/staleness.py`

```text
veritx_dse.gateway.staleness — detect a gateway serving stale code.

WHY THIS EXISTS
---------------

The gateway is a long-lived process started WITHOUT ``--reload``. Backend
commits therefore do not reach a running process, and the failure is
silent and misleading: the process keeps answering 200 with payloads built
by the OLD code.

That has already caused two real incidents:

  * a Compile Result white-screen, because a freshly compiled revision
    returned the pre-change certificate claim shape (no
    ``contributing_obligations``) from a process started hours before the
    fix was committed;
  * the same class of failure once more after the fix landed, because the
    process was still the old one.

The lesson is that "remember to restart" is not a control. This module
makes staleness OBSERVABLE: at startup the process records the newest
source mtime it was loaded from, and any later request can compare it
against the source on disk. A process whose code has been edited underneath
it reports itself as stale instead of quietly lying.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/vnext.py`

```text
veritx_dse.gateway.vnext — Studio vNext product routes.

New routes only. Existing routes are untouched; this module is hooked
into the app by a single ``register_vnext_routes(app)`` call in
``create_app``. Handlers parse, validate API shape and delegate to
``veritx_dse.product.vnext`` — no scientific semantics live here.
```


# `gateway` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py`

line 58:

```text
    # NOTE: `repo` here is tracks/t3-topology, and the store/runs/experiments
    # paths below are correctly relative to it — the studio store really does
    # live at tracks/t3-topology/runs/studio-store. It is NOT the repository
    # root, so it must not be used to locate vendored third-party trees.
```

line 118:

```text
        # P5 step 8: the prompt asks for an honest backend summary. The
        # sealed P2 law stands — health reports install facts
        # (PRESENT/ABSENT), never readiness: READY requires adjudicating
        # a real canonical context, which health must not do. Ramulator
        # joins the summary on identical terms (extension present or
        # not); no simulation ever runs here.
```

line 226:

```text
    #: Search budget. `None`/omitted = exhaustive. PHASE 1: these were not
    #: expressible on the product API at all, so a caller could not bound a
    #: large search.
```

line 265:

```text
# OptimizeBody and the deprecated ``POST /optimize`` endpoint were removed
# (PF-D15, STUDIO-WIREFRAMES.md §181). The canonical optimization surface is
# ``POST /api/v1/revisions/{revision_id}/optimize`` — a study against an
# immutable revision. The legacy endpoint took a raw request + ad-hoc domain
# and bypassed revision identity and StudyDefinition/DesignSpace separation.
```

line 874:

```text
    # Typed failures are registered as exception handlers so Starlette's
    # ExceptionMiddleware returns the mapped status (only the bare Exception
    # case falls through to the 500 ServerErrorMiddleware).
```

## `tracks/t3-topology/dse/veritx_dse/gateway/staleness.py`

line 14:

```text
#: Recorded when this module is first imported — i.e. when the process
#: loaded the code. Any source file newer than this was written AFTER the
#: process started and is therefore NOT running.
```


# `gateway` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py` :: `CompileDraftBody`

```text

    ``expected_draft_design_hash`` is the snapshot the user reviewed. The
    gateway refuses with ``STALE_REVIEW`` when the current canonical draft
    no longer matches it, so a reviewed snapshot can never compile unseen
    content. No ETag substitute: the canonical content hash is the
    authority the draft model already uses.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py` :: `resolve_booksim_bin`

```text

    BUG THIS FIXES. The gateway read VERITX_BOOKSIM_BIN and passed None when
    it was unset, WITHOUT falling back to find_booksim_bin(). Every other
    consumer falls back (fabric_evaluator, the studio fixture generator,
    backend/booksim). So on a machine with a built, working BookSim the
    gateway alone reported the backend as

        MISSING - "no qualified backend configured (set VERITX_BOOKSIM_BIN)"

    and refused every evaluation, while the same binary ran fine from the
    CLI and the tests. The message named an environment variable as the
    remedy when the real problem was a missing fallback in this module.

    The search uses core.paths.REPO, the single source of truth for the
    REPOSITORY root. `config_from_env`'s local `repo` is tracks/t3-topology
    (correct for the store paths, wrong for vendored third-party trees), so
    passing it here would look for the binary one level too high.

    Returns None only when the binary genuinely does not exist, so MISSING
    now means missing rather than unset.
```


# `gateway` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py` :: `_compile_design`

```text

    * a v3 ``request`` document compiles through ``FabricCompiler`` directly;
    * a guided ``preset`` compiles through ``SrotaControlPlane`` (which
      commits a resolution) and is projected through ``FabricCompiler``; the
      two identities are asserted equal so there is no second authority.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py` :: `v1_health`

```text

        The gateway runs without --reload, so a backend commit does not
        reach a running process and the failure is silent: the process keeps
        answering 200 with payloads built by the OLD code. `code.stale` is
        True when a source file on disk is newer than this process, which
        means a restart is required before any response can be trusted.
```

## `tracks/t3-topology/dse/veritx_dse/gateway/app.py` :: `v1_optimization_capabilities`

```text

        The Studio derives its controls from THIS. Nothing here is
        hand-maintained in the frontend: guided parameters, search methods,
        selection policies and certified metrics all come from canonical
        backend definitions, and `topology_family` values are obtained by
        asking the canonical materializer rather than restating an enum.
```
