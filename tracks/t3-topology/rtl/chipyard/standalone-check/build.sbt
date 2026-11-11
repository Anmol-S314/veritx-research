ThisBuild / scalaVersion := "2.13.10"
ThisBuild / organization := "veritx.check"

// Standalone check for the repo-owned Chisel router/policy sources.
// It compiles only these files; it does not vendor or replace Chipyard.
lazy val routerCheck = (project in file("."))
  .settings(
    name := "veritx-chipyard-router-check",
    Compile / unmanagedSourceDirectories := Seq.empty,
    Compile / unmanagedSources := Seq(
      baseDirectory.value.getParentFile / "SynthAssert.scala",
      baseDirectory.value.getParentFile / "CreditRouter.scala",
      baseDirectory.value.getParentFile / "NativeRoutePolicy.scala",
      baseDirectory.value.getParentFile / "HybridCreditRouter.scala",
      baseDirectory.value / "EmitHybridRouter.scala"
    ),
    Test / unmanagedSourceDirectories := Seq.empty,
    Test / unmanagedSources := Seq(
      baseDirectory.value.getParentFile / "tests" / "CreditRouterSpec.scala",
      baseDirectory.value.getParentFile / "tests" / "HybridCreditRouterSpec.scala",
      baseDirectory.value.getParentFile / "tests" / "HybridRoutePolicySpec.scala",
      baseDirectory.value.getParentFile / "tests" / "SrotaInjectionPolicySpec.scala",
      baseDirectory.value.getParentFile / "tests" / "SrotaCreditTelemetrySpec.scala"
    ),
    libraryDependencies ++= Seq(
      "edu.berkeley.cs" %% "chisel3" % "3.6.1",
      "edu.berkeley.cs" %% "chiseltest" % "0.6.0" % Test,
      "org.scalatest" %% "scalatest" % "3.2.15" % Test
    ),
    addCompilerPlugin("edu.berkeley.cs" % "chisel3-plugin" % "3.6.1" cross CrossVersion.full),
    scalacOptions ++= Seq("-language:reflectiveCalls", "-deprecation"),
    Test / parallelExecution := false
  )
