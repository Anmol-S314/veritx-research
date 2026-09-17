VeriTX Control-Plane Redesign

Implementation Handoff and Adversarial Architecture Review

Status: Implementation-ready direction, with deliberate discovery points

---

## IMPLEMENTATION STATUS — audited 2026-09-17 (suite: 869 passed, 1 skipped)

Phase scoreboard (§30 / §33). Evidence lives in docs/adr/, SEMANTIC_QUESTIONS.md,
dse/veritx_dse/, dse/tests/, and HANDOFF-2026-09-16-evening.md ADDENDA 1–7.

| §30 Phase | §33 PR | Status | Evidence |
|---|---|---|---|
| 0 repair Bash baseline | PR 1 | DONE | pre-2026-09-16-evening; see HANDOFF-2026-09-16-PM.md (all §1 defects fixed + regression tests) |
| 1 freeze invariants | — | DONE | docs/adr/0001..0006 — exactly the six ADRs §30 lists; no speculative-architecture ADRs |
| 2 golden corpus | PR 2 | DONE (BookSim part) | dse/tests/test_golden_booksim.py; serving goldens intentionally wait for Slices B/C |
| 3 BookSim vertical slice | PR 2+3 | DONE | core/spec.py (strict boundary; comparison §19 + replication §20 IN the spec), core/runs.py (immutable runs, state machine, atomic writes, env-allowlisted provenance), core/experiment.py run_experiment e2e on the real binary (test_slice_a_booksim.py) |
| 4 LLMServingSim→BookSim | PR 5+6 | NOT STARTED | blocked on protocol fixture; §34 groundwork DONE: SEMANTIC_QUESTIONS.md Q1–Q7,Q10,Q11 answered from vendored source; Q12 lists the 6 open ones (livelock diagnostics required before Slice B) |
| 5 LLMServingSim→ASTRA | PR 7 | NOT STARTED | needs Phase 4 first (§6 order) |
| 6 extract shared mechanics | (PR 4) | PARTIAL | core/process.py supervised_run — first §7-justified extraction (process ownership, TERM→KILL, bounded capture); PR 4's API frozen; serving sessions will reuse PIECES, not the one-shot API (§4.2) |
| 7 thin Python CLI | PR 8 | NOT STARTED | veritx CLI today is the legacy surface, not the thin adapter |
| 8 migrate remaining ops | — | NOT STARTED | t3 Bash still owns sweep/compare/trace/report |
| 9 local index | — | NOT STARTED | runs/index.db is the LEGACY index; §14's rebuildable .veritx/index.db unwritten (correct — artifacts first) |
| 10 TUI | — | NOT STARTED | t3 Bash TUI still owns UI |
| 11 coordinator | — | NOT STARTED | correctly so (§29: no daemon until real concurrent clients) |
| 12 MCP | — | NOT STARTED | correctly so |

§31 Definition-of-Done, item by item: DONE = BookSim-through-Python (1), inputs
immutable after start (7), provenance automatic+allowlisted (8), stochastic
replication explicit (11), golden corpus passes (16), run identity/atomic writes
(§3.1–3.5 all). PARTIAL = execution-context consistency (4: t3 astra path unified,
_timeloop_env provenance rule, supervised groups — but Bash still switches
contexts), INTERRUPTED diagnosability (6: state exists, no recovery classifier),
comparison validity (10: ComparisonSpec parsed, not yet enforced across legacy
sweep JSONs), machine JSON (12: manifests stable, legacy outputs not), agent
boundary (15: ADR + nothing exposed yet), t3 migration bookkeeping (17).
NOT STARTED = serving paths (2,3), thin CLI (13), TUI (14), index deletion (18,
vacuously safe today).

Net position: the FOUNDATION (invariants, identity, strict boundary, supervision,
BookSim slice) is complete and tested; the migration is at "one vertical slice
proven, second awaiting its protocol fixture" — the exact gate §30 sets before
any generalization. 856→869 tests added without breaking the legacy seam.

NEXT ACTIONS (in order):
1. PR 5: fake-backend protocol fixture (real process; modes incl.
   waiting-without-progress), encoding ONLY SEMANTIC_QUESTIONS.md-confirmed facts;
   module named llmservingsim_protocol.py — no InteractiveRunner.
2. PR 6: Slice B serving run using that fixture; settle Q12.1 diagnostics first.
3. Then §6 Slice C, and only then the §7 deletion-test review.

---
Primary objective: Replace the current 2,700+ line Bash control plane with a smaller, testable, reproducible, agent-friendly Python control plane without performing a speculative framework rewrite.

0. Read This First

This document is intentionally opinionated about invariants and observable behavior, but intentionally conservative about internal abstractions.

Do not begin by creating a hierarchy of Runner, Backend, Repository, Manager, Provider, Factory, or Service classes. The current architecture became difficult partly because too many responsibilities accumulated in one place; the opposite failure would be replacing it with dozens of shallow abstractions whose boundaries were guessed before the concrete execution paths were understood.

The implementation strategy is:

Make the concrete cases correct first. Once two or more concrete cases repeat the same semantics, compress that repetition behind a small, deep interface.

This follows the semantic-compression principle: make code usable before making it reusable. It also follows the deep-module/deletion-test style from Matt Pocock's architecture guidance: an abstraction is justified when removing it would scatter meaningful complexity, not merely because two functions look vaguely similar.

The architecture must emerge from at least these real execution paths:

Standalone BookSim experiment

LLMServingSim -> BookSim

LLMServingSim -> ASTRA analytical

Later: RTL/Verilator path, if/when migrated

These paths are deliberately different enough to expose bad abstractions early.

1. Current Problem

The current t3 Bash script is no longer merely a launcher. It currently owns or partially owns:

command routing

CLI dispatch

guided builders

terminal UI

web-command dispatch

Docker entry/escape logic

native execution

ASTRA-Sim special cases

VeritX command discovery

environment-variable translation

output/result-directory semantics

persistent UI state

toolchain checks

lint/self-check behavior

result discovery

plotting/report launch paths

model/workload selection

LLMServingSim launch configuration

This is too much semantic responsibility for shell code.

Known concrete defects found during the audit include:

ASTRA-Sim host-special-case invocation loses user arguments.

ASTRA-Sim works differently depending on whether the path originated on the host, in the TUI container, or through web command dispatch.

_veritx_sub positional parsing can fail under set -u and misinterpret subcommands.

several trace builders can generate duplicated verbs such as trace slice slice.

custom T3_RESULTS/T3_OUTPUT behavior can be forwarded and then overwritten.

lint can report warnings while returning success.

check is not a strong preflight/CI gate.

generic comparison flows can permit scientifically incomparable configurations.

interactive command parsing can lose shell quoting.

some menu selection/paging behavior is incorrect.

result/config provenance is currently insufficiently authoritative for long-term reproducibility.

The redesign must fix these causes rather than merely reimplementing current behavior in Python.

2. What VeriTX Actually Contains

Do not flatten all components into the word "backend".

The system currently has several semantic layers:

2.1 Workload / serving-system model

LLMServingSim belongs here.

It models things such as:

serving requests

request lifecycle

scheduler behavior

batching

model instances

TP placement

serving/router decisions

generation/progression over simulated time

Crucially, LLMServingSim communicates with its network/simulation side through a long-lived interactive subprocess protocol, including commands/replies such as load, run, pass, exit, and Waiting-terminated responses.

That makes it architecturally different from a simulator that is invoked once, writes output, and exits.

2.2 Network / communication simulation

Examples include:

BookSim

ASTRA analytical/network backend behavior

These may be used directly by an experiment or indirectly beneath LLMServingSim.

2.3 RTL / detailed implementation model

Examples may include:

Verilator RTL NoC simulation

This has different performance, build, and execution semantics again.

2.4 Execution environment

Separate this concept from the simulator itself:

host/native

Docker/container

future remote/HPC execution

For example:

BookSim may run in a container.

ASTRA may currently need native execution due to host/container library compatibility.

the same simulator type could theoretically have more than one execution environment later.

Do not conflate simulator semantics with process-location semantics.

3. Architecture Principles That Are Non-Negotiable

These are architectural invariants. Unlike class structure, they should be decided before implementation because violating them can silently corrupt research results.

3.1 Every run has a unique identity

Every realized execution receives a unique run_id.

Recommended: ULID or UUIDv7-like sortable IDs.

Example:

01K5FQXA2EX7...

A rerun of the exact same experiment receives a new run ID.

3.2 Scientific intent has a stable identity

The fully resolved experiment specification must be canonicalized and hashed.

experiment_hash = SHA256(canonical_resolved_spec)

This answers:

Were these executions intended to be the same scientific experiment?

while run_id answers:

Which actual execution produced these artifacts?

3.3 A started run is immutable

Once execution starts:

its resolved specification cannot change;

its input references cannot be silently rebound;

resume may not mix results produced from different effective specifications.

If a user changes a setting, create a new run.

3.4 Files on disk are authoritative

The authoritative research record is the immutable run directory and its manifests/artifacts.

A database may index runs later, but deletion/corruption of that index must never destroy the ability to reconstruct the research history.

3.5 Important writes are atomic

Never update authoritative JSON state by truncating and rewriting the live path directly.

Use a same-filesystem temporary file and atomic rename/replacement.

For important metadata, optionally fsync before rename where practical.

3.6 Provenance is automatic

Official results may not depend on the user remembering to enable provenance.

Capture relevant provenance automatically and safely.

3.7 No dynamically constructed shell execution

Do not use shell=True in the execution layer.

Use argv arrays.

Bad:

subprocess.run(f"booksim {cfg} > {out}", shell=True)

Good:

subprocess.run([booksim_path, cfg_path], ...)

3.8 A child process has one explicit owner

Any native process or container started by VeriTX must have one lifecycle owner responsible for:

PID/container ID

stdout

stderr

exit code

timeout

cancellation

SIGTERM

escalation to SIGKILL where necessary

cleanup/orphan handling

UI cancellation is not equivalent to process cancellation.

3.9 Resume requires a dependency fingerprint match

Never use:

if result_file.exists():
    skip()

A reusable task output must match the complete dependency fingerprint, including relevant:

task specification

input content hashes

simulator/binary/container identity

code/version identity

configuration identity

A mismatch requires recomputation or an explicit user decision. No silent reuse.

3.10 Persisted formats are versioned

Every persisted data model must contain a schema version.

Examples:

{"schema_version": 1}

This applies to at least:

experiment specifications

resolved plans

manifests

task state

results

comparison protocols

3.11 Machine output is stable and separate from human output

In machine mode:

stdout = structured machine data only

stderr = progress/logging

no ANSI

no spinner

no prompts

no mixed prose and JSON

3.12 Agents do not receive arbitrary execution primitives

Agents should invoke semantic operations, not shell commands.

Do not expose agent tools such as:

arbitrary shell

arbitrary Docker invocation

arbitrary host paths

arbitrary binary paths

arbitrary environment injection

3.13 Scientific comparison declares intent explicitly

A comparison must declare:

what variable(s) are intentionally changing;

what dimensions must remain controlled;

which differences are acknowledged consequences of the topology/design itself.

A comparison is not valid merely because two result JSON files exist.

4. Important Correction: There Is Not One Universal Execution Model

A major architectural risk would be assuming every workload can be represented by:

argv -> process -> result -> exit

That is false because of LLMServingSim.

4.1 One-shot execution

Standalone BookSim may approximately behave like:

prepare config
   -> launch process
   -> wait
   -> parse result
   -> done

This is naturally modeled as a process invocation.

4.2 Interactive session execution

LLMServingSim's backend relationship behaves more like:

spawn backend
    |
load ...
    |
read until protocol boundary
    |
run ...
    |
read until Waiting/terminal reply
    |
pass ...
    |
...
    |
exit

This requires:

persistent stdin/stdout

protocol framing

command/reply sequencing

progress/liveness semantics

protocol timeout handling

detection of EOF/broken pipe

careful ownership of both serving loop and backend process

Therefore:

Do not prematurely invent a universal run_process() abstraction and force LLMServingSim through it.

A reusable process primitive may emerge for common lifecycle mechanics, but the interaction protocol must remain a first-class behavior.

5. Recommended Early Code Shape

Start small.

A reasonable first Python package may be only:

src/veritx/
    spec.py
    plan.py
    run.py
    process.py
    results.py
    booksim.py
    astra.py
    llmserving.py
    cli.py

This is an initial working shape, not a permanent architecture contract.

Avoid creating these until concrete duplication proves them necessary:

interfaces/
abstract/
factories/
providers/
repositories/
managers/
services/
plugins/

Do not create base.py solely because two implementations exist.

6. Concrete Vertical Slices

Build concrete vertical slices before extracting common machinery.

Slice A: Standalone BookSim

Target public behavior:

spec -> validate -> plan -> run -> result

Make the simplest real BookSim experiment work end-to-end.

The slice should include:

strict experiment input parsing

deterministic resolved spec

run ID creation

run directory creation

provenance

process launch

stdout/stderr capture

timeout handling

cancellation behavior

atomic final state

result parsing

Do not generalize for ASTRA yet.

Slice B: LLMServingSim -> BookSim

Implement this independently enough to expose its true needs.

This slice must model the interactive protocol explicitly.

Tests must cover at least:

normal startup

one load/run/pass progression

backend EOF

backend non-zero exit

malformed reply

missing Waiting terminator

request deadlock/livelock timeout behavior

explicit shutdown

parent cancellation

child that ignores graceful termination

The known multi-instance livelock makes this slice especially important. The new control plane must not hide or paper over serving-loop semantic bugs behind generic timeout guardrails.

Slice C: LLMServingSim -> ASTRA analytical

Implement the same serving semantics with a different network backend path.

This is the strongest early architecture test because:

the serving semantics should remain the same;

backend/network-specific behavior differs;

execution environment may differ;

the same high-level experiment should still produce a coherent run record.

Only after A/B/C work should shared mechanisms be extracted.

7. Semantic Compression Rules

When two or more concrete slices repeat meaningful behavior, inspect the repetition.

Examples of repetition that may justify extraction:

create run directory
write immutable resolved spec
capture provenance
write stdout/stderr
record exit status
atomic state transitions
terminate child/process group

This may justify a deep run/process module.

But similarity alone is not enough.

Use the deletion test:

If this abstraction were deleted, would complex semantics be duplicated in several locations?

If yes, the abstraction may be deep and valuable.

If deleting it only causes two short readable call sites to gain five obvious lines each, leave the code concrete.

8. Domain Vocabulary

Create a concise CONTEXT.md and maintain terminology deliberately.

Initial proposed vocabulary:

Experiment

Scientific intent: workload/system/network variables and comparison intent.

Resolved experiment

Experiment after defaults, references, presets, and derived values have been materialized into explicit values.

Run

One realized execution of a resolved experiment.

Task

A separately executable unit inside a run, where such decomposition actually exists.

Simulator

A simulation implementation, e.g. BookSim, ASTRA component, Verilator-based model.

Execution environment

Where/how a process runs, e.g. native host or container.

Serving model

The higher-level serving-system model, currently LLMServingSim.

Result

Structured scientific output produced by a run/task.

Artifact

Any associated file: logs, traces, generated configs, raw simulator output, plots, etc.

Comparison protocol

The explicit declaration of experimental variable(s), controlled dimensions, and accepted structural differences.

These names are provisional. Adjust them when existing code reveals a better domain term, but once decided, use them consistently across code, docs, CLI, and agent tools.

Avoid multiple words for the same concept such as backend, engine, runtime, and provider unless they truly denote different concepts.

9. Experiment Specifications

Use strict boundary validation.

Pydantic is suitable at the parsing boundary, but do not couple the entire internal domain to Pydantic models.

Recommended behavior:

strict type validation

reject unknown fields

no silent string-to-number coercion for scientific parameters

clear validation errors

explicit schema version

Example:

schema_version: 1
name: qwen3_decode_n64

workload:
  id: qwen3_decode_64

system:
  nodes: 64
  tp_size: 1
  instances_per_node: 2

network:
  topology: mesh_8x8
  routing: dim_order

simulation:
  mode: serving
  serving_model: llmservingsim
  network_simulator: booksim

replication:
  mode: deterministic

Do not support complex YAML inheritance initially.

If composition is needed, use explicit references/presets, then materialize the complete resolved specification into the run directory before execution.

The resolved specification is what gets hashed.

10. Run Directory Layout

A suggested shape:

runs/
└── 01K5FQXA2EX7...
    ├── manifest.json
    ├── spec.resolved.json
    ├── plan.json
    ├── provenance.json
    ├── state.json
    ├── stdout.log
    ├── stderr.log
    ├── artifacts/
    ├── tasks/
    │   └── ...
    └── result.json

Do not require tasks/ for a run that genuinely has no useful task decomposition.

The artifact layout should serve the real execution model, not force every run into a workflow-engine shape.

11. State Model

Use an explicit run lifecycle rather than combinations of boolean fields.

Potential states:

CREATED
VALIDATED
PLANNED
RUNNING
SUCCEEDED
FAILED
CANCELLED
INTERRUPTED

Do not add states unless a concrete behavior needs them.

Each state transition should have clear rules.

Example:

RUNNING -> SUCCEEDED only after result finalization succeeds.

process exit 0 alone does not imply SUCCEEDED if result parsing/finalization fails.

abrupt control-plane death may leave a run requiring recovery classification.

When retries are needed, do not overwrite previous attempts. Preserve attempt history.

12. Crash Recovery

The design must assume:

terminal closes

Python crashes

Docker daemon restarts

simulator crashes

host reboots

disk fills

Ctrl-C occurs during a write

On startup/recovery, VeriTX should be able to examine a run marked RUNNING and determine at minimum:

Is its child process/container still alive?

Is this process the legitimate owner?

Are authoritative result artifacts complete?

Should the run be marked INTERRUPTED?

Do not automatically resume arbitrary stale runs at first.

A safe initial policy is:

detect orphaned/stale RUNNING state;

classify it as INTERRUPTED;

require explicit resume/retry;

reuse only verified task outputs whose fingerprints match.

This is safer than aggressive automatic recovery.

13. Concurrency Model

Phase 1: single writer

Do not introduce a mandatory coordinator daemon yet.

For the first implementation:

one VeriTX process owns a run;

use a workspace/run lock where needed;

reject conflicting writers;

allow multiple read-only consumers when safe.

This drastically reduces the initial state-space.

Future: persistent coordinator

When CLI + TUI + web + agents truly need simultaneous control, introduce one local coordinator/daemon (veritxd) that owns:

scheduling

process/container lifecycles

state transitions

cancellation

resource accounting

Then interfaces become clients:

CLI ---\
TUI ----> veritxd
Web ---/
MCP --/

Do not let multiple FastAPI workers independently launch jobs.

14. SQLite Policy

Do not use SQLite as the authoritative run store.

Reason:

future NFS/shared-filesystem usage can make SQLite WAL assumptions invalid;

multi-host coordination may arrive later;

research provenance should remain reconstructable from immutable artifacts.

Use SQLite only as an optional, rebuildable local index:

.veritx/index.db

If it is deleted:

veritx index rebuild

must reconstruct it from run manifests.

If genuine multi-host coordination is needed later, evaluate PostgreSQL or another service DB at that time.

15. Provenance Requirements

Capture at least:

VeriTX Git commit

dirty/clean state

dirty patch hash or equivalent fingerprint where practical

resolved experiment specification hash

input trace/content hashes

topology/config hashes

Python version

dependency lock/environment identity

simulator version

executable SHA256 for native simulator binaries where practical

container image digest, not only mutable tag

relevant shared-library/version identity for native binaries where necessary

host OS/kernel metadata where scientifically relevant

execution environment type

actual argv

start/end timestamps

seed(s)

exit status

Do not blindly dump the entire environment because it may leak credentials.

Use an allowlist for environment provenance.

16. Native vs Container Reproducibility

Container pinning alone does not solve native ASTRA reproducibility.

For a native simulator capture at least:

binary SHA256

reported version

resolved config hashes

important shared library/version information when relevant

execution host fingerprint

If ASTRA later becomes containerizable in a compatible environment, that may improve reproducibility, but do not block the control-plane redesign on it.

17. LLMServingSim Protocol Boundary

The serving/backend protocol deserves its own tests and likely its own concrete module.

Do not leak raw protocol strings throughout the codebase.

However, also do not immediately invent a large object protocol hierarchy.

First write one correct protocol implementation with explicit operations.

Potential concrete API:

session = ServingBackendSession(...)
session.start()
session.load(...)
reply = session.run(...)
reply = session.pass_(...)
session.close()

Whether this exact object survives should be determined after the BookSim and analytical paths both use it.

Important protocol behaviors to define:

command termination

reply termination

what Waiting means

EOF semantics

timeout semantics

invalid protocol state

process death

startup failure

graceful close

forced close

A livelock must remain observable as a serving/protocol/scheduler problem. Do not "solve" correctness failures by merely adding wall-clock kill timers and reporting success/failure vaguely.

Timeouts are safety boundaries, not root-cause fixes.

18. Resource and Runaway Protection

Agent friendliness requires hard server-side limits.

An agent can accidentally create an experiment such as:

128 topologies * 100 injection rates * 30 seeds = 384,000 simulations

Typed schemas do not prevent this.

Implement policy limits such as:

maximum tasks per run

maximum parallel tasks

maximum total requested runtime

maximum generated output estimate if available

maximum trace expansion

configurable confirmation threshold for expensive runs

These limits must be enforced by VeriTX, not merely described in agent instructions.

19. Comparison Correctness

Do not implement comparison validity as "all configs must have equal fields".

Topology research intentionally changes structural dimensions.

Use an explicit comparison protocol.

Example:

comparison:
  variable:
    - topology

  controlled:
    workload: same
    node_count: same
    traffic_trace: same
    packetization: same
    offered_load: same
    routing_policy: same
    flit_width: same

  acknowledged_differences:
    - radix
    - link_count
    - hop_count

Then validation can detect unexpected differences such as:

VC count:
  mesh = 2
  torus = 4

and mark the comparison invalid or require explicit acknowledgement.

The comparison layer should explain why two runs are or are not directly comparable.

20. Randomness and Replication

Do not blindly use seeds=5 as a universal default.

Explicitly model randomness.

Examples:

replication:
  mode: deterministic

or:

replication:
  mode: stochastic
  seeds: [101, 102, 103, 104, 105]

Where feasible, simulators should expose known randomness sources.

For stochastic comparisons, result summaries should retain per-run data and report appropriate dispersion (e.g. mean, standard deviation, confidence interval where justified).

Do not aggregate away the raw replicate results.

21. Process Supervision

Build process supervision carefully before building fancy UI.

At minimum it must support:

argv-array launch

process group/session ownership

stdout streaming/capture

stderr streaming/capture

timeout

graceful terminate

forced kill escalation

exit-code capture

detection of broken pipe/EOF

cleanup on parent cancellation

For Docker/container execution, record the container identity and perform equivalent lifecycle management.

A frontend worker/coroutine cancellation is not sufficient unless it propagates to the real OS/container process.

22. Result and Event Model

Events are useful for observation:

{"type":"run.started","run_id":"..."}
{"type":"task.started","task_id":"..."}
{"type":"task.completed","task_id":"..."}

They can feed:

CLI progress

TUI

web sockets

agents

logs

But do not make an event log the sole authoritative state representation.

Authoritative state should remain materialized in run/task metadata and result files.

Also, do not route high-rate simulation hot-path events such as per-flit activity through Python control-plane events. That would destroy performance and blur the responsibility boundary.

23. Agent Interface

The repository should become agent-friendly before MCP exists.

Create:

AGENTS.md
CONTEXT.md
docs/adr/

Keep AGENTS.md short.

Example:

# VeriTX agent instructions

Read CONTEXT.md before changing experiment semantics.

Run tests:
  uv run pytest

Do not:
- use shell=True
- mutate completed run artifacts
- bypass comparison validation
- expose arbitrary shell execution to agents

Architecture decisions:
  docs/adr/

Use ADRs only for significant hard-to-reverse decisions.

Do not create a giant permanent instruction file.

24. Future MCP Interface

MCP should be a thin adapter over stable semantic operations.

Potential tools:

list_capabilities
list_topologies
describe_topology
list_workloads
validate_experiment
plan_experiment
execute_plan
get_run
get_results
compare_runs
cancel_run

Never expose:

shell(command)
docker_run(...)
run_binary(path,...)
write_file(any_path,...)

Plan/execute separation

For agents, separate:

validate -> plan -> execute

A plan should have a stable identity/hash.

execute_plan(plan_id) must execute the validated plan, not silently accept changed parameters.

This prevents validation/execution drift.

25. Trusted Configuration vs Agent-Editable Scientific Intent

Keep machine/execution configuration separate from experiment intent.

Trusted project config may contain:

binary locations

container image/digest

mount policy

simulator environment

allowed execution environment

Agent-editable experiment specs should not directly control:

arbitrary executable paths

arbitrary mounts

host paths

arbitrary environment variables

LD_LIBRARY_PATH

shell fragments

Agents choose registered semantic IDs and scientific parameters.

26. Testing Strategy

Do not freeze internal implementation details with excessive unit tests.

Prioritize stable public seams.

Level 1: specification/planning tests

Given an experiment spec:

strict validation is correct;

resolved spec is deterministic;

hash is stable;

comparison protocol validation is correct;

plan expansion is correct.

Level 2: real process-supervision fixture

Create tiny fake executable fixtures rather than mocking subprocess.Popen.

Provide fake simulators that:

succeed

exit non-zero

hang

ignore SIGTERM

emit malformed output

emit huge stderr

close stdout unexpectedly

partially write results

This tests the real OS boundary.

Level 3: LLMServingSim protocol fixture

Create a fake interactive backend implementing the same stdin/stdout protocol.

Cases:

valid command/reply

delayed Waiting

missing terminator

malformed reply

EOF

crash

hang

shutdown

This allows deterministic testing of serving-loop integration without expensive BookSim/ASTRA execution.

Level 4: tiny real simulator golden tests

Maintain a tiny deterministic corpus:

one standalone BookSim experiment

one LLMServingSim -> BookSim experiment

one LLMServingSim -> analytical experiment

Validate scientifically meaningful outputs, not merely stdout strings.

Level 5: Bash/Python migration parity

During migration, run corrected Bash and Python implementations against the same tiny corpus.

Differences require explicit classification:

expected improvement/change

bug in Bash

bug in Python

simulator nondeterminism

Do not assume either implementation is automatically the oracle.

27. Failure Cases the Architecture Must Survive

The following should be explicit acceptance scenarios.

Process failures

simulator exits before producing output

simulator exits 0 but output is malformed

parent receives Ctrl-C

child ignores SIGTERM

Docker container remains alive after parent dies

stdout pipe closes

stderr floods

backend protocol stalls

Filesystem failures

disk full during log write

disk full during result finalization

half-written temporary file

result directory already exists unexpectedly

permissions failure

input trace disappears after plan creation

input contents change after planning

Version/provenance failures

mutable Docker tag points to a new image

native ASTRA binary changes

Git working tree is dirty

simulator config changes between planning/execution

old result uses older schema

Resume/cache failures

stale output exists with different seed

task result exists from older simulator binary

run interrupted after simulator exit but before final manifest update

one task completed and another did not

Concurrency failures

two terminals attempt same run

TUI and CLI attempt mutation simultaneously

future web worker attempts independent scheduling

Scientific failures

compare 64-node and 72-node systems accidentally

VC counts differ unexpectedly

injection semantics differ

stochastic route run has one seed

deterministic run is wastefully repeated

Agent failures

agent generates an enormous sweep

agent attempts arbitrary host path

agent invents topology ID

agent retries failed runs indefinitely

agent tries to bypass comparison validation

LLMServingSim-specific failures

single-instance works but multi-instance livelocks

backend-independent serving failure

scheduler repeatedly makes no progress

Waiting is interpreted incorrectly

backend command/reply protocol desynchronizes

frontend/backend simulated clocks diverge

The architecture must preserve enough information to debug these rather than merely timing out.

28. Progress/Livelock Diagnostics

Because LLMServingSim has already exhibited extremely fast no-progress spinning, add observability, not arbitrary success guardrails.

Record/debug counters that can expose:

serving loop iterations

simulated-time advancement

requests admitted/completed

scheduler state changes

backend commands sent

backend replies received

outstanding work

per-instance progress

A diagnostic should be able to distinguish:

wall-clock slow

from:

simulated time is not advancing

from:

simulated time advances but no request completes

from:

backend repeatedly returns Waiting with unchanged state

A timeout may terminate a pathological run, but the run must record diagnostic state that makes root-cause analysis possible.

29. What NOT to Build Yet

Do not add these during the first migration unless a demonstrated requirement appears:

PostgreSQL

Redis

Celery

Airflow

Prefect

Dagster

Kubernetes

generic plugin system

generic workflow DSL

mandatory daemon

remote execution

arbitrary MCP shell

complex YAML inheritance

huge web dashboard rewrite

universal simulator base class

All of these expand the state-space before the local execution model is proven.

30. Migration Sequence

Phase 0 - Repair the current baseline

Fix known Bash correctness bugs first.

At minimum:

ASTRA argument forwarding

ASTRA TUI/web/native execution inconsistency

_veritx_sub

malformed trace builder commands

custom result directory semantics

lint/check exit codes

interactive quoting issue

menu paging/selection issue

unreachable/duplicated command branches

Add regression tests where possible.

The goal is not to perfect Bash. The goal is to establish a trustworthy behavioral baseline for migration.

Phase 1 - Freeze only system invariants

Write short ADRs for:

immutable runs

experiment/run identity

filesystem-authoritative artifacts

resume fingerprint semantics

trusted execution config vs scientific experiment config

agent no-shell boundary

Do not write ADRs for speculative class structure.

Phase 2 - Golden corpus

Create tiny, fast, deterministic fixtures for:

standalone BookSim

LLMServingSim -> BookSim

LLMServingSim -> analytical backend

one failure/interruption case

Store expected scientifically meaningful behavior.

Phase 3 - Python BookSim vertical slice

Implement concrete standalone BookSim end-to-end.

No generic runner framework.

Phase 4 - LLMServingSim -> BookSim vertical slice

Implement explicit interactive protocol behavior.

Focus on process ownership and no-progress diagnostics.

Phase 5 - LLMServingSim -> ASTRA analytical vertical slice

Prove the serving/session boundary survives a second backend path.

Phase 6 - Semantic compression

Compare A/B/C implementation code.

Extract only proven repeated semantics.

Likely candidates may include:

run initialization/finalization

provenance

atomic state writes

process supervision

artifact helpers

Do not assume the final names beforehand.

Phase 7 - Python CLI

Use Typer or another straightforward CLI layer.

CLI should be thin.

Preserve t3 as a compatibility shim temporarily.

Example final shim:

#!/usr/bin/env bash
exec uv run veritx "$@"

or direct installed binary invocation.

Phase 8 - Migrate remaining operations vertically

Migrate:

sweep

compare

trace operations

workload operations

reports

one slice at a time.

Each migration should delete corresponding Bash logic when stable.

Avoid permanent dual implementations.

Phase 9 - Local index

After run artifacts are stable, add rebuildable SQLite indexing if it materially improves discovery.

Phase 10 - TUI

Replace manual Bash UI with Textual only after core operations are stable.

The TUI must contain no simulator/scientific logic.

Phase 11 - Multi-client coordinator, only if required

Introduce veritxd only when simultaneous CLI/TUI/web/agent mutation becomes a real requirement.

Phase 12 - Agent/MCP adapter

Expose stable semantic operations.

Read-only operations first, then planning, then controlled execution.

31. Definition of Done for the Control-Plane Migration

The migration is not done merely because Bash is gone.

It is done when:

standalone BookSim executes through Python correctly;

LLMServingSim -> BookSim works through Python;

LLMServingSim -> ASTRA analytical works through Python;

execution context no longer changes command semantics silently;

Ctrl-C reliably terminates owned children/containers;

interrupted runs remain diagnosable;

run inputs are immutable after start;

provenance is sufficient to reproduce/identify the environment;

stale resume outputs cannot silently contaminate a run;

comparison validity is explicit;

stochastic replication policy is explicit;

machine JSON output is stable;

the CLI is a thin adapter;

the TUI, if present, is a thin adapter;

agents cannot invoke arbitrary shell/process primitives;

the tiny golden corpus passes;

old t3 compatibility behavior has either been migrated or deliberately removed/documented;

deleting the local index does not lose authoritative run history.

32. Implementation Discipline for the Agent

When implementing this plan:

Do not perform a big-bang rewrite.

Do not invent abstraction layers to make the tree look clean.

Keep concrete paths readable.

Create an abstraction only after repeated working cases reveal it.

Prefer functions/data over class hierarchies unless stateful behavior genuinely requires an object.

Keep the public experiment/run seam small.

Test observable behavior, not private implementation details.

Every migration step should be runnable and reviewable.

Do not hide scientific differences behind generic configuration objects.

Do not solve serving livelocks with guardrails alone. Find and preserve root-cause observability.

Do not silently normalize invalid/unknown experiment fields. Reject them.

Do not silently reuse stale outputs.

Do not add infrastructure because it may be useful later.

When uncertain, implement the concrete case and revisit abstraction after the second real example.

33. Suggested First Pull Requests

Keep changes independently reviewable.

PR 1 - Bash stabilization

Fix the known t3 bugs and add smoke/regression coverage.

PR 2 - Experiment/run schema + immutable run skeleton

No simulator execution yet.

Demonstrate:

spec -> resolved spec -> hash -> run directory -> manifest

PR 3 - Concrete standalone BookSim Python execution

End-to-end tiny run.

PR 4 - Process failure/cancellation fixtures

Fake executables; verify lifecycle behavior.

PR 5 - LLMServingSim protocol fixture

Fake interactive backend and protocol tests.

PR 6 - LLMServingSim -> BookSim Python execution

Do not generalize prematurely.

PR 7 - LLMServingSim -> ASTRA analytical Python execution

Now compare duplication and extract only obvious shared semantics.

PR 8 - Thin Python CLI + t3 compatibility forwarding

Only after core paths are correct.

34. Questions the Agent Must Not Guess About

If the current repository does not make the following semantics clear, inspect the code/tests and document the answer before implementing behavior:

exact LLMServingSim stdin/stdout protocol framing

exact meaning of Waiting

which process owns simulated time advancement

expected ordering constraints for load/run/pass

whether BookSim/analytical behavior is synchronous or session-like in each integration

what constitutes successful completion of a serving run

authoritative location of existing model/topology presets

which existing outputs are treated as canonical by downstream scripts

precise random-number sources and seed propagation

simulator-specific units for latency/time/bandwidth metrics

whether two comparison modes intentionally use different semantics

Do not infer scientific semantics from command names alone.

35. Explicit Risks That Remain

Even after this redesign, several unavoidable risks remain.

Risk: Python itself becomes another monolith

Mitigation:

keep public seams few;

use semantic compression after concrete repetition;

apply deletion test during refactors;

do not centralize every operation in run.py forever.

Risk: process-management complexity is underestimated

Mitigation:

real fake-process fixtures;

explicit process ownership;

test hanging/ignoring children;

test container cleanup.

Risk: experiment hashing is unstable

Mitigation:

canonical serialization;

resolved values only;

stable ordering;

exclude irrelevant presentation fields from scientific hash only if explicitly defined;

test hash stability.

Risk: scientific equivalence rules are wrong

Mitigation:

comparison protocol is explicit and reviewable;

do not bury equivalence assumptions in generic validation code;

retain full resolved specs with results.

Risk: native ASTRA runs are harder to reproduce

Mitigation:

capture binary/config/library fingerprints;

later evaluate container/Apptainer packaging.

Risk: migration causes behavior drift

Mitigation:

corrected Bash baseline;

golden corpus;

parallel parity period;

classify every difference.

Risk: LLMServingSim protocol remains tightly coupled

Mitigation:

test protocol independently with fake backend;

keep protocol behavior concrete until at least two network backend paths prove the common seam.

Risk: agent can create valid but absurd experiments

Mitigation:

server-side budgets;

plan-before-execute;

task-count/resource estimates;

explicit expensive-run policy.

Risk: single-writer v1 eventually blocks product evolution

Mitigation:

run artifacts/state designed so a future coordinator can own the same semantics;

do not embed UI assumptions in core;

introduce daemon only when actual concurrent clients require it.

36. Final Architectural Position

The target is not "rewrite Bash in Python."

The target is:

A small experiment control plane with immutable, reproducible run records; explicit serving/network simulator semantics; strong process ownership; explicit scientific comparison intent; and narrow interfaces that both humans and agents can use safely.

The implementation method is equally important:

Build concrete vertical slices first. Compress only repeated semantics after they are proven. Prefer a few deep modules over many shallow abstractions.

The three most important acceptance paths are:

Standalone BookSim
LLMServingSim -> BookSim
LLMServingSim -> ASTRA analytical

If those three are simple, reproducible, cancellable, diagnosable, and share only abstractions that emerged naturally, the architecture is on the right track.

If implementing the third path requires bypasses, special global flags, shell escape hatches, or large conditional branches inside a supposedly generic abstraction, stop and revisit the abstraction rather than adding another exception.

37. Reference Principles Used

This plan incorporates two useful bodies of guidance:

Semantic compression / bottom-up reuse: implement concrete working cases first and extract shared semantics only after actual repetition exists. Do not design reusable abstractions from hypothetical examples.

Deep-module and agent-oriented engineering guidance: prefer a small number of meaningful public seams, use the deletion test to identify valuable modules, keep domain vocabulary explicit, test behavior at public seams, and use progressive disclosure for agent documentation.

These are principles, not external frameworks. VeriTX should not depend on either source at runtime.

Immediate instruction to the implementation agent

Start with Phase 0 and Phase 2. Do not scaffold the final Python package architecture first.

Before creating new abstractions, produce:

a corrected Bash baseline;

a tiny golden test corpus;

a short CONTEXT.md defining only terminology that is already clear from the repository;

a list of unresolved semantic questions discovered from LLMServingSim/BookSim/ASTRA code;

the first standalone BookSim vertical slice.

After the BookSim and both LLMServingSim-backed paths exist, perform an explicit architecture review and only then extract shared modules.
