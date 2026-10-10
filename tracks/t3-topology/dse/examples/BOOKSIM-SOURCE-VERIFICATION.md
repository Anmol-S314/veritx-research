# BookSim source-build verification (diagnostic only)

This tooling reproduces the **actual working-tree source**, including dirty,
ignored and untracked inputs. It never creates a clean git checkout, writes a
BuildManifest, replaces a binary/pin, activates a qualification record or
changes the git index. `DIAGNOSTIC_UNQUALIFIED` remains the outcome even if
both builds have identical bytes and every native check passes.

From the repository root (output directory must not exist):

```sh
PYTHONDONTWRITEBYTECODE=1 python scripts/verify_booksim_source_build.py \
  --output-root /tmp/veritx-booksim-source-verification \
  --cxx /usr/bin/g++ --cc /usr/bin/gcc
PYTHONDONTWRITEBYTECODE=1 python scripts/verify_booksim_source_build.py \
  --verify-report /tmp/veritx-booksim-source-verification/verification.json
```

Requires make, explicit C++/C compilers, flex, bison, Python and the repository's
pytest/DSE dependencies. Missing tools, build/test failure, timeout, source
or tool drift, incomplete evidence and (by default) byte mismatch fail closed.
Timeouts kill the complete build/test process group (POSIX/Linux), not just
its wrapper. There are no acceptance skips for unavailable build tools. All build products,
logs, native inputs and evidence are external. Native execution consumes the
original canonical parent fixtures; it does not define another lowerer.

## Snapshot and build contract

- Sorted inventory records path, SHA256, byte count and executable-bit status
  of **every non-generated regular file** below `--source-root` (default
  `third_party/booksim2/src`). No git archive, gitignore or tracked-file filter
  hides modified, untracked or ignored inputs. This intentionally includes
  non-build fixtures/docs/scripts too, so changes there also trigger drift.
- Explicit omissions: `booksim`, `booksim.build-manifest.json`, `lex.yy.c`,
  `y.tab.c`, `y.tab.h`, suffixes `.o/.d/.a/.pyc`, and `.git/__pycache__/.pytest_cache`
  directories. Actual omitted paths are reported. Parser sources regenerate
  from `config.l/config.y`. The standalone Makefile must remain authoritative;
  this recipe does not support deliberately treating generated product names
  as hand-authored build inputs. All symlinks and special files refuse.
- Inventory matches original inputs before/after copying, both copied sources
  after building, original inputs after native execution, and re-verification.
  A content snapshot is **not** a clean reviewed revision.
- Both builds run external `make -j2 booksim`, with explicit CC/CXX/LEX/YACC,
  explicit `CPPFLAGS` and empty `LFLAGS`. Flags are `-Wall`, existing include
  directories, `-O3 -g`, plus `-ffile-prefix-map/-fdebug-prefix-map` mapping
  each build directory to `/veritx/booksim-src`. This is a **distinct recipe**
  `booksim-source-snapshot-debug-prefix-map/v1`, not byte reproducibility of
  the old unnormalized debug recipe. Make/compiler/parser versions and
  executable hashes, effective command/flags, build environment, statuses
  and log digests are retained. Build environment is PATH, LC_ALL/LANG=C,
  SOURCE_DATE_EPOCH=0; ambient CFLAGS/MAKEFLAGS are not inherited.
- Git HEAD, producer-scoped status and whole-repository status are recorded
  honestly. Failed discovery is `null`, never clean. No snapshot git commit
  or fake revision is created. Whole-tree status is archival; re-verification
  checks source-scoped facts/revision and content, allowing unrelated changes.
- Optional `--container-digest IMAGE@sha256:...` records a **caller-supplied,
  unverified identity**, not proof of actual execution inside that container.
  Tool executable hashes/versions do not pin linked libraries, OS or host.
- `--build-only` explicitly omits native diagnostics. `--allow-byte-mismatch`
  allows successful *diagnostic execution* with `byte_identical=false`, never
  a reproducibility/equivalence claim. Default mode requires equal SHA/size/
  executable-bit facts across the two independently copied builds.

## Native checks on each exact binary

Default mode runs three focused tests plus the current native SROTA live ledger
regression, with no tool skips:

1. Cmesh c=2 and c=4: actual canonical terminal bindings, every endpoint's
   ejection seat, independent XY next-router law at every source router,
   executed route comparison and full packet/flit conservation. c=2 rejects
   express routing; c=4 rejects n=3. Historical c=4 express code is **not**
   mislabelled as a native unsupported-routing guard.
2. Class-VC: exact class0->VC1/class1->VC0 observations with nonzero counts,
   per-class/total conservation, negative/upper/reversed bounds, short/long
   tables, wrong routing, negative/upper foreign trace classes all refuse.
3. SROTA: the existing native-owned dyadic token/hold/refund/spend and upstream
   credit ledger runs throttled/bypass/depth-one/original-time variants and
   horizon/tamper counterexamples on each exact binary. This checks current
   modelling-wave producer instrumentation, not abstract/native equivalence.

Every cmesh/class-VC summary binds the binary hash, prepared identity and full
existing diagnostic execution record. Configs, traces, route dumps, positive
raw repeat logs, negative logs and ledger evidence are retained/digest-bound.
The generic supervised executor retains parsed evidence, not raw logs; a
separately identified repeat native invocation therefore captures raw output
and must reproduce exactly the parsed stats and route dump of the supervised
execution. It is not labelled the original execution's raw output.

The report also binds Python verification/parent-fixture implementation inputs
(all DSE `.py`, this script and the explicit cmesh example), checking drift
across native runs. `--verify-report` rehashes retained sources/tools/artifacts,
verifies complete artifact coverage, input/provenance/binary identity and native
summary coverage. It does **not** rerun simulation or constitute cryptographic
attestation against an adversary rewriting the entire report and artifacts.
Keep the report and directories together; source/tool/code drift fails replay.

## Clean qualification prerequisite (not automated here)

An owner must provide a real reviewed source revision containing the selected
producer changes, a clean attributable checkout, and approved immutable
compiler/C compiler/parser/container identities. Current HEAD does not contain
all dirty producer changes; prohibitions on staging/committing/reset/stash
prevent creating that checkpoint. Do not publish snapshot builds as clean.

After a clean build and all exact-scope positive/negative native gates with no
skips, independent review must approve durable digest-bound evidence. Publishing
new binary/BuildManifest pins and activating cmesh or class-VC qualification
records require separate owner authorization. Re-pinning alone does not qualify
a profile. Standalone class-VC does not solve the distinct embedded ASTRA ABI.
Reference RCU/multicast/escape and V5 abstract execution do not imply producer
support. Existing pins and NOT_QUALIFIED/withdrawal records remain unchanged.
RTL/UVM/physical signoff, fairness and full-fabric schedule equivalence are not
part of this verification.
