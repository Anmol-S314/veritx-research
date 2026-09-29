# `cli` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/cli/cli.py`

```text
veritx — unified CLI for the VeritX NoC DSE pipeline.

Usage:
    veritx trace chakra <et_dir> --nodes 64 --out runs/traces/input.trace
    veritx trace model <json> --nodes 64 --out runs/traces/input.trace
    veritx trace info <trace>
    veritx trace extract <trace> --burst 100 --out ...
    veritx trace extract <trace> --uniform --out ...
    veritx trace slice --trace <trace> --classes 0,1 --out ...
    veritx trace validate <trace>
    veritx synthesize bo --traffic <trace> --nodes 64 --iters 50
    veritx evaluate booksim --trace <trace> [--k 8] [--routing dor]
    veritx evaluate anynet --topo <anynet> --trace <trace>
    veritx evaluate astra --ets <et_dir> [--timeout 300]
    veritx certify flow --model <json> --topo <anynet>
    veritx certify rtl --topo <anynet> [--tier quick]
    veritx certify full --model <json> --topo <anynet>
    veritx run --model <json> --nodes 64 [--search bo] [--cert flow]
    veritx sweep --trace <trace>
    veritx compare --trace <trace> --topos mesh,torus
    veritx compare --trace <trace> --dense llama70b_ring
    veritx pareto --traces <t1,t2> --topos mesh,torus
    veritx runs [--last N] [--run-id <id>]
    veritx results [--last N]
    veritx status [--last N]
    veritx diff [run_a] [run_b]
    veritx report --json <results.json>
    veritx compile --preset mesh4 --policy baseline_deterministic_v2 \
        --store runs/canonical-store [--set noc_config.link_width=128]

Pipeline: trace → synthesize → evaluate → certify → done
All evaluation uses trace-replay mode (correct timestamps, no Bernoulli).
```

## `tracks/t3-topology/dse/veritx_dse/cli/commands_compile.py`

```text
veritx_dse.cli.commands_compile — thin CLI adapter for canonical compile.

Transport and presentation ONLY for the public ``veritx compile`` command:

    CLI declaration
          |
          v
    CompileIntent
          |
          v
    SrotaControlPlane.compile()
          |
          v
    canonical service path
          |
          v
    CompileOutcome

``cli.py`` owns the argparse declaration and dispatch;
``SrotaControlPlane`` owns orchestration. This module owns exactly:

* parsing ``--set PATH=JSON_SCALAR`` override strings;
* loading an exact persisted CompileIntent (``--intent``);
* constructing ``CompileIntent`` / ``ResourceStore`` / ``SrotaControlPlane``;
* calling ``compile()``;
* formatting the presentation summary.

It never compiles anything itself: no CompileRequest construction, no
topology/routing/VC derivation, no canonical compiler call, no BookSim, no
verification, no UVM/RTL/report generation. BookSim execution is a later,
separate slice.

Expected declaration errors (malformed ``--set``, invalid intent document,
service failure, store failure) propagate to the CLI's top-level handler,
which reports them cleanly and exits non-zero without a traceback. This
module does not catch broad exceptions and does not swallow programmer
bugs.
```

## `tracks/t3-topology/dse/veritx_dse/cli/commands_optimize.py`

```text
veritx_dse.cli.commands_optimize — ``veritx optimize`` product surface.

Thin CLI over the existing optimizer: grid/random search over GUIDED
fabric parameters, every candidate through the real certified evaluator
(compile → qualified BookSim → authenticated evidence), Pareto +
selection, schema-valid study view. No new search, no new evaluator, no
new metric — the optimizer owns all of that.
```

## `tracks/t3-topology/dse/veritx_dse/cli/pipeline.py`

```text
veritx_dse.pipeline — High-level pipeline orchestration.

Composes booksim + traces modules into complete workflows:
  - Full pipeline (trace → synthesize → evaluate → certify)
  - Multi-workload Pareto comparison
  - Run history and diff
  - LaTeX report generation
```


# `cli` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/cli/cli.py`

line 81:

```text
# ── Command handlers ────────────────────────────────────────────────────────
# Each function: parse args → call module → print result.
# NO business logic. NO sys.exit. Exceptions propagate to main().
```

line 463:

```text
        # A non-zero exit is authoritative even when no PASS/FAIL line was
        # emitted: without this, a certifier that crashed silently counted as
        # "0 failed" and the command reported success.
```

line 771:

```text
        # THE EXACT GRAPH THAT WAS SYNTHESIZED.
        #
        # This step previously derived k from `args.nodes` (falling back to
        # k=8 whenever the count was not a perfect square) and evaluated a
        # freshly constructed mesh. The design EVALUATED was therefore not
        # the design SYNTHESIZED: two different identities in one run, and a
        # silent substitution whenever the node count did not fit a square.
```

line 808:

```text
                    # AUTHORITATIVE verdict: the process result and its
                    # structured status. NOT a substring scan of stdout —
                    # `any("PASS" in line)` passes on a log line that merely
                    # mentions PASS (including "FAIL: expected PASS").
```

line 1660:

```text
    # ── compile (canonical product compile surface) ──────────────
    # Vocabulary is derived from the authorities: preset names from
    # preset_names(), policy values from CandidatePolicy. No duplicate list.
```

line 1870:

```text
    # A command that REPORTED a failure must not exit 0. Handlers call
    # `fail()` and return normally, so without this the process reported
    # success while printing errors.
```

## `tracks/t3-topology/dse/veritx_dse/cli/commands_compile.py`

line 17:

```text
# Optional preset-only declaration options are refused together with
# --intent: this mode consumes an exact persisted snapshot, never a merge.
# (label, argparse attribute) pairs.
```

## `tracks/t3-topology/dse/veritx_dse/cli/pipeline.py`

line 90:

```text
    # Trace's highest addressed node feeds the anynet size pre-check below.
    # Parsed lazily: pure-preset batches never pay for it, and an unreadable
    # trace defers its diagnosis to the real run.
```

line 96:

```text
        # Custom-graph pre-check (RECLAIMED generic safety). BookSim HANGS on
        # a disconnected anynet and can dribble out a near-empty result that
        # would otherwise rank as a real number. Skip with an error record —
        # no summary row, no bogus rank. The decision lives in ONE reusable
        # authority, `presets.anynet_usability`, not inlined here.
```

line 133:

```text
                # VeritX: rank on honest latency (arrival - trace timestamp).
                # The stock plat mean is qtime-based: qtime slots go stale
                # across idle gaps, inflating sparse-trace means 100x+.
```

line 165:

```text
        # VeritX: prefer honest latency (see above); fall back to the plat
        # mean when the binary predates honest_avg (e.g. ASTRA-backed
        # results). Non-numeric latencies never enter the mean.
```

line 188:

```text
            # A failed candidate must stay VISIBLE in the comparison:
            # silent exclusion hides exactly the runs that invalidate the
            # comparison (e.g. a 16-node topology against a 64-node trace).
            # The entry carries the first error; the printer renders it and
            # the winner selection ignores it (no numeric mean).
```

line 270:

```text
    # Save — LOAD-BEARING in this tree: `show_results` reads
    # runs/booksim/compare_*.json and nothing else writes it. The stronger
    # lineage moved persistence to its command layer; the current command
    # layer does not persist, so the removal is NOT reclaimed.
```

line 440:

```text
                # A failed/partial row is still part of the study record and
                # must render. Assuming every row carries
                # mean/std/min/max/n crashed the whole command on one failure.
```

line 481:

```text
    # Resolve run arguments to actual directories.
    # - A full path or existing dir is used as-is.
    # - A bare run_id is looked up inside the experiments dir.
    # - An omitted side is filled from the newest runs ONLY when both sides
    #   are omitted; otherwise an unresolvable side is an ERROR (the old
    #   `_resolve_run(...) or runs[0]` silently diffed the wrong pair).
```

line 568:

```text
        # `veritx sweep` output: bare list of per-topology results
        # [{name, latency, hops, edges, ...}]. Prefer honest latency
        # (arrival - trace timestamp) over the qtime-based plat mean.
```


# `cli` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/cli/cli.py` :: `_uvm_generation_input`

```text

    Two defects this closes:

    * the size came from `--nodes`/`--k`, defaulting to 64/8, so a testbench
      could describe a fabric that has nothing to do with the design;
    * only a v2 `CompileRequest` was accepted, so a v3 revision document could
      not be used at all even though v3 is what the product produces.

    The size is now taken from the canonical materialized topology. A v3
    request is REFUSED with a clear reason rather than silently generated
    from a guessed size — `generate_uvm` still derives its VC structure with
    the v2 path, and pretending otherwise would emit collateral for a design
    nobody compiled.
```

## `tracks/t3-topology/dse/veritx_dse/cli/pipeline.py` :: `run_compare`

```text

    topo_specs: list of (display_name, Topology) pairs.
    Returns CompareResult with per-topology aggregation.

    LEGACY, UNCERTIFIED COMPARISON SURFACE. This is the pre-product CLI
    comparison. It is NOT a qualified product comparison: the canonical
    comparability gate is `application.comparison` over typed results
    (`core/comparison.py` is classified LEGACY_INTERNAL in
    application/inventory.py). `print_compare_table` labels its winner
    claim accordingly so the two cannot be confused.
```


# `cli` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/cli/cli.py` :: `cmd_baseline`

```text

    Baselines (standard configurations from literature):
      - mesh_8x8:     2D mesh k=8 n=2, dim_order routing (TPU v1/v2 style)
      - torus_8x8:    2D torus k=8 n=2, dim_order routing
      - flatfly_64:   FlatButterfly k=4 n=2 c=4 (UFusion style)
      - ring_64:      Ring topology (Gpipe/PipeDream style)
      - star_64:      Star/hub topology (central switch)
      - gec_express:  GEC express k=8 o=7 d=1 (our best BO result)
```

## `tracks/t3-topology/dse/veritx_dse/cli/commands_optimize.py` :: `_parse_clock_hz`

```text

    The evaluation core accepts only exact int/None clocks (float Hz
    would make wall-time claims inexact). An integral decimal/scientific
    string such as "1e9" is parsed EXACTLY (``Fraction``), never through
    binary float: ``float("9007199254740993")`` silently becomes
    9007199254740992, so a frequency would move without anyone changing
    it. Non-integral or non-finite strings refuse here at the CLI
    boundary, never inside the science.
```

## `tracks/t3-topology/dse/veritx_dse/cli/pipeline.py` :: `print_compare_table`

```text

    LABELLED NON-CANONICAL. This is the legacy CLI comparison surface. The
    canonical comparability verdict lives in `application.comparison` over
    typed results (see `application/inventory.py`, which classifies
    `core/comparison.py` as LEGACY_INTERNAL). Reclaiming the historical
    Phase-8 verdict block here would resurrect a second comparison
    authority, so instead the winner claim is explicitly marked
    UNCERTIFIED and pointed at the qualified path.
```
