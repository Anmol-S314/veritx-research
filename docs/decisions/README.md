# Design decisions (extracted from code)

This directory holds the *why* that used to live in module docstrings and
inline comments across `veritx_dse` (and later `apps/studio` / track scripts).
Rationale, history, and cross-references belong here; code keeps only short,
load-bearing comments.

## Policy

When de-bloating a module:

1. **Move** rationale, history, slice numbers, incident post-mortems and
   "why this exists" essays into a topic file here (one file per package or
   subsystem, or one per module when it is large).
2. **Keep** comments that state an *invariant the code enforces* or a
   *safety/refusal rule* — usually one line, e.g. `# fail-closed: refuse a
   route table that is not total`. These are contracts, not prose.
3. **Delete** comments that restate the code, narrate the edit, or duplicate
   the doc you just moved.
4. Keep the module docstring short: one-line purpose + a pointer to the
   relevant `docs/decisions/*.md`.
5. Public API docstrings keep their behavioural contract (args, raises,
   refusal vocabulary); they lose design essays.
6. Never change code tokens in a de-bloat edit. Verify with the module's
   tests / `py_compile` / `pytest --collect-only`.

## Index

| Decision doc | Extracted from |
|---|---|
| [capability-truth.md](capability-truth.md) | `veritx_dse/application/capability_truth.py` |
| [synthesis.md](synthesis.md) | `veritx_dse/synthesis/*` |
| [compute-memory-intent.md](compute-memory-intent.md) | compute/memory v4 intent — proposed |
| [studio.md](studio.md) | `apps/studio/src/*` file headers |
