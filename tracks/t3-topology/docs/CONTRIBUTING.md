# Contributing to VeritX

## Getting Started

```bash
cd tracks/t3-topology/dse
pip install -e .
python3 -m pytest -v  # verify everything works
```

## Project Structure

```
veritx_dse/
├── cli.py              # Entry point — arg parsing + dispatch ONLY
├── logging.py          # Ctx dataclass (replaces globals)
├── presets.py          # Topology + workload definitions
├── booksim.py          # BookSim2 integration
├── traces.py           # Trace I/O (pure functions)
├── pipeline.py         # Orchestration (compare, sweep, run)
├── compile_model.py    # Data model (E1-E5, guardrails, VC derivation)
├── reports.py          # Area/power/timing estimation
├── artifact.py         # Signing + manifest
├── evaluator.py        # Legacy BookSim runner
├── bo_synthesizer.py   # Bayesian optimization
└── traffic_model.py    # Phase-aware traffic model

tests/
├── test_prd_gaps.py        # Tests for reports, artifact, compile_model
├── test_compile_model.py   # Tests for E1-E5, VC derivation, guardrails
└── test_cli_modules.py     # Tests for booksim, traces, logging
```

## Design Rules

### 1. No Globals

Every function takes a `Ctx` parameter or returns a result. No module-level state.

```python
# ✓ Good
def my_function(ctx: Ctx, args) -> Result:
    log(ctx, "doing something")
    return Result(...)

# ✗ Bad
_verbosity = 1  # global state
def my_function():
    print("doing something")  # uses global
```

### 2. No sys.exit() in Commands

Command functions raise exceptions. `main()` catches them.

```python
# ✓ Good
def cmd_my_command(ctx: Ctx, args):
    if not valid:
        fail(ctx, "error message")
        return  # or raise BookSimError(...)

# ✗ Bad
def cmd_my_command(ctx: Ctx, args):
    if not valid:
        sys.exit(1)  # kills the process
```

### 3. Frozen Dataclasses

All data types are immutable after creation.

```python
@dataclass(frozen=True)
class MyType:
    field: str
    count: int = 0
```

### 4. Single Source of Truth

- Topologies → `presets.py` (one `Topology` instance per topology)
- Data types → `compile_model.py` (one `dataclass` per entity)
- Config building → `booksim.py` (one `build_config()` function)

### 5. TDD

Write tests first. Implementation follows.

```python
# test_my_feature.py
def test_my_feature():
    from veritx_dse.my_module import my_function
    result = my_function(input)
    assert result.ok is True
    assert result.value > 0
```

## Adding a New Module

1. Create `veritx_dse/my_module.py`
2. Write tests in `test_my_module.py`
3. Import in `cli.py` and wire into a command
4. Update `__init__.py` module list

## Adding a New Topology

Add one `Topology` instance to `SWEEP_TOPOS` in `presets.py`:

```python
Topology(
    name="my_topo_8x8",
    backend="mesh",           # BookSim topology type
    routing="min_adapt",      # BookSim routing function
    params={"k": 8, "n": 2},  # BookSim config overrides
    needs_noc_latency_zero=False,
)
```

All commands automatically discover it.

## Adding a New Agent Kind

Add to `AgentKind` enum in `compile_model.py`:

```python
class AgentKind(Enum):
    COMPUTE_TILE = "compute_tile"
    HBM_CONTROLLER = "hbm_controller"
    MY_NEW_KIND = "my_new_kind"  # ← add here
```

## Adding a New Dependency Kind

Add to `DepKind` enum in `compile_model.py`:

```python
class DepKind(Enum):
    BLOCKING = "blocking"
    ORDERING = "ordering"
    INDEPENDENT = "independent"
    MY_NEW_KIND = "my_new_kind"  # ← add here
```

## Adding a New Report Type

1. Add estimation function to `reports.py`
2. Wire into `generate_report()` return dict
3. Add accuracy note to `accuracy_notes`
4. Test in `test_prd_gaps.py`

## Running Tests

```bash
# All tests
python3 -m pytest tracks/t3-topology/dse/ -v

# Specific module
python3 -m pytest tracks/t3-topology/dse/test_prd_gaps.py -v

# Quick check
python3 -m pytest tracks/t3-topology/dse/ -q
```

## Code Style

- Type hints on all public functions
- Docstrings with PRD section references (e.g., `"""PRD §7.1: ..."""`)
- `from __future__ import annotations` at top of every file
- f-strings for formatting
- No imports at module level in `cli.py` (lazy imports inside functions)

## Common Patterns

### Pattern: Pure function with typed result

```python
@dataclass(frozen=True)
class MyResult:
    ok: bool
    value: float
    errors: list[str] = field(default_factory=list)

def compute_something(input: str) -> MyResult:
    """PRD §X.Y: Description."""
    if not valid:
        return MyResult(ok=False, value=0, errors=["invalid input"])
    return MyResult(ok=True, value=42.0)
```

### Pattern: Command handler

```python
def cmd_my_command(ctx: Ctx, args):
    """Handler for 'veritx my-command'."""
    result = my_function(args.input)
    if not result.ok:
        fail(ctx, f"Failed: {result.errors}")
        return
    ok(ctx, f"Result: {result.value}")
    output(ctx, result.to_dict())
```

### Pattern: BookSim config

```python
config = build_config(topo, trace, sample_period=200)
result = run_booksim(ctx, config, repo_root=REPO, timeout=60)
latency = result["latency"]
```
