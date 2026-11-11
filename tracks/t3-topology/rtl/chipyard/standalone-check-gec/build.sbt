ThisBuild / scalaVersion := "2.13.10"
ThisBuild / organization := "veritx.check"

// Elaborates selected GEC previews against an exported contract. GEC_CONTRACT_DIR
// must contain SelectedGec.scala, contract.json and resources/selected-gec.bin
// from veritx_dse.product.chipyard_gec.export_contract.
lazy val gecPreview = (project in file("."))
  .settings(
    name := "veritx-chipyard-gec-preview-check",
    Compile / unmanagedSourceDirectories := Seq.empty,
    Compile / unmanagedSources := {
      val contract = sys.env.getOrElse("GEC_CONTRACT_DIR", "")
      require(contract.nonEmpty, "GEC_CONTRACT_DIR must point at an exported GEC contract")
      Seq(
        baseDirectory.value.getParentFile / "CompiledGecPreview.scala",
        baseDirectory.value.getParentFile / "CompiledGecCreditPreview.scala",
        baseDirectory.value.getParentFile / "GecContractData.scala",
        baseDirectory.value.getParentFile / "CreditRouter.scala",
        baseDirectory.value.getParentFile / "CreditRouterExt.scala",
        baseDirectory.value.getParentFile / "SynthAssert.scala",
        file(contract) / "SelectedGec.scala"
      )
    },
    Compile / unmanagedResourceDirectories := {
      val contract = sys.env.getOrElse("GEC_CONTRACT_DIR", "")
      require(contract.nonEmpty, "GEC_CONTRACT_DIR must point at an exported GEC contract")
      Seq(file(contract) / "resources")
    },
    Test / unmanagedSources := Seq(
      baseDirectory.value.getParentFile / "tests" / "CompiledGecCreditPreviewSpec.scala"
    ),
    libraryDependencies ++= Seq(
      "edu.berkeley.cs" %% "chisel3" % "3.6.1",
      "edu.berkeley.cs" %% "chiseltest" % "0.6.0" % Test,
      "org.scalatest" %% "scalatest" % "3.2.15" % Test
    ),
    addCompilerPlugin("edu.berkeley.cs" % "chisel3-plugin" % "3.6.1" cross CrossVersion.full),
    scalacOptions ++= Seq("-language:reflectiveCalls", "-deprecation"),
    Test / fork := false,
    Test / parallelExecution := false
  )
