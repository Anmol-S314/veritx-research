package veritx.chipyard

import chisel3.stage.ChiselStage
import java.nio.file.{Files, Paths}

object EmitHybridRouter extends App {
  System.setProperty("veritx.synthesize", "1")
  val cfg = CreditRouterConfig(
    inputs = 1,
    taps = Seq(1),
    vcs = 1,
    width = 8,
    depth = 2,
    outputDepth = 1,
    iterations = 1,
    tagBits = 8
  )
  val target = args.lastOption.getOrElse("generated-hybrid-router")
  val sv = ChiselStage.emitSystemVerilog(new HybridCreditRouter(cfg))
  Files.createDirectories(Paths.get(target))
  Files.write(Paths.get(target, "HybridCreditRouter.v"), sv.getBytes("UTF-8"))
}
