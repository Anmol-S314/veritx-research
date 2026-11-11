package veritx.chipyard

import chisel3._
import chisel3.stage.ChiselStage

/** Black-box view of one pre-emitted router body.
  *
  * Elaborating `CreditRouter` 81 times puts 81 router bodies in the FIRRTL
  * IR, because Chisel builds one module per `Module` instance.  At the selected
  * shape one 17x17/8-VC body is 16.3 MB of IR, so 81 of them is ~1.7 GB and the
  * elaborator runs out of heap.  A black box has no body: Chisel records an
  * `extmodule`/`inst` pair instead, and the Verilog emitter deduplicates the 81
  * stubs to a single module name.  The emitter writes that body once per
  * *distinct config* (the selected contract has two) beside the top.
  */
class CreditRouterExt(c: CreditRouterConfig, nm: String)
    extends BlackBox with CreditRouterLike {
  override def desiredName: String = nm
  // A BlackBox drops its outer `io` field from the port names.  The extra
  // level keeps the ports named `io_in_*`, the same as the regular module, so
  // the top can instantiate either one with identical connections.
  val io = IO(new Bundle { val io = new CreditRouterIO(c) })
  def routerIo: CreditRouterIO = io.io
}

object CreditRouterEmit {
  /** Stable module name for a router shape, including a digest of every
    * parameter that changes the emitted body. */
  def moduleName(c: CreditRouterConfig): String = {
    val digest = java.security.MessageDigest.getInstance("SHA-256")
      .digest(c.toString.getBytes("UTF-8"))
      .take(6).map("%02x".format(_)).mkString
    s"CreditRouter_${c.inputs}x${c.taps.size}_${c.vcs}vc_$digest"
  }

  /** The concrete body emitted for one config. */
  class Body(c: CreditRouterConfig, name: String) extends CreditRouter(c) {
    override def desiredName: String = name
  }

  /** Every distinct body in one circuit.
    *
    * All shapes must be emitted together: Chisel gives the internal modules of
    * each router the same names (`Queue`, `CreditMatch`, `CreditOwnership`,
    * `RRArbiter`), so two separate `ChiselStage` runs write two Verilog files
    * that both define `module Queue` with different widths and cannot be
    * compiled together.  In one circuit those names are made unique
    * (`Queue`, `Queue_1`, ...) across every shape.
    */
  class Bodies(configs: Seq[CreditRouterConfig]) extends Module {
    require(configs.nonEmpty)
    val n = configs.size
    val maxWidth = configs.map(_.width).max
    val maxVcBits = configs.map(_.vcBits).max
    val maxSlotBits = configs.map(_.slotBits).max
    val maxTagBits = configs.map(_.tagBits).max
    // Every router input is driven from a top-level input.  Tying them to
    // constants would let the FIRRTL compiler propagate the constants into the
    // router modules and prune the allocator and the per-VC queues, emitting a
    // body that is functionally empty.  Live inputs keep the body intact.
    val io = IO(new Bundle {
      val live = Input(Vec(n, Bool()))
      val data = Input(Vec(n, UInt(maxWidth.W)))
      val vc = Input(Vec(n, UInt(maxVcBits.W)))
      val head = Input(Vec(n, Bool()))
      val tail = Input(Vec(n, Bool()))
      val tag = Input(Vec(n, UInt(maxTagBits.W)))
      val slot = Input(Vec(n, UInt(maxSlotBits.W)))
      val routeValid = Input(Vec(n, Bool()))
      val routeTag = Input(Vec(n, UInt(maxTagBits.W)))
      val creditValid = Input(Vec(n, Bool()))
      val creditTail = Input(Vec(n, Bool()))
      val probe = Output(UInt(1.W))
    })
    val sinks = configs.zipWithIndex.map { case (c, r) =>
      val body = Module(new Body(c, moduleName(c)))
      body.io.in.foreach { p =>
        p.valid := io.live(r)
        p.bits.data := io.data(r)(c.width - 1, 0)
        p.bits.vc := io.vc(r)(c.vcBits - 1, 0)
        p.bits.head := io.head(r)
        p.bits.tail := io.tail(r)
        p.bits.tag := io.tag(r)(c.tagBits - 1, 0)
      }
      body.io.route.foreach { x =>
        x.slot := io.slot(r)(c.slotBits - 1, 0)
        x.valid := io.routeValid(r)
        x.tag := io.routeTag(r)(c.tagBits - 1, 0)
      }
      body.io.credit.foreach { x =>
        x.valid := io.creditValid(r)
        x.bits.tail := io.creditTail(r)
      }
      // Keep every output live so the bodies are not reduced to empty modules.
      dontTouch(body.io.returned); dontTouch(body.io.routeHead); dontTouch(body.io.out)
      dontTouch(body.io.free); dontTouch(body.io.occupied); dontTouch(body.io.inputOccupancy)
      body.io.occupied.asUInt
    }
    io.probe := sinks.reduce(_ ^ _)
  }

  /** Emit all distinct router bodies to `targetDir`; return their module names. */
  def emitBodies(configs: Seq[CreditRouterConfig], targetDir: String): Seq[String] = {
    val distinct = configs.distinct
    val previous = Option(System.getProperty("veritx.synthesize"))
    System.setProperty("veritx.synthesize", "1")
    try {
      (new ChiselStage).emitVerilog(new Bodies(distinct), Array("--target-dir", targetDir))
    } finally {
      previous match {
        case Some(value) => System.setProperty("veritx.synthesize", value)
        case None        => System.clearProperty("veritx.synthesize")
      }
    }
    distinct.map(moduleName)
  }
}
