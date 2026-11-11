# Router/policy check

Standalone sbt project for the Chisel sources in the parent directory. It is
**not** part of the exported Chipyard source bundle: `product/chipyard_sources.py`
copies only named files, and this directory is never included.

## Pinned toolchain

| Item | Version |
|---|---|
| sbt | 1.10.7 |
| JDK | 17 (Temurin 17.0.21 used) |
| Scala | 2.13.10 |
| Chisel | 3.6.1 |
| chiseltest | 0.6.0 |
| ScalaTest | 3.2.15 |

JDK 25 cannot compile the Scala 2.13.10 compiler bridge
(`scala.reflect.internal.FatalError` in `ClassfileParser.errorBadIndex`).
Use JDK 17.

## Run

From the repository root:

```text
JAVA_HOME=/path/to/jdk17 bash scripts/check_chipyard_router.sh
```

The script enforces the 3 GiB heap / one-CPU cap:

```text
SBT_OPTS=-Xmx3G -XX:ActiveProcessorCount=1
```

Expected suites: `CreditRouterSpec` (3), `HybridRoutePolicySpec` (5),
`SrotaInjectionPolicySpec` (7), `SrotaCreditTelemetrySpec` (5).

## Scope

These are Chisel-level unit checks. They do **not** elaborate Chipyard or
Constellation, do not synthesize, and are not hardware qualification.
`tests/KNCubeSourceSpec.scala` is excluded because it needs the external
Constellation source tree, which is not part of this checkout.
