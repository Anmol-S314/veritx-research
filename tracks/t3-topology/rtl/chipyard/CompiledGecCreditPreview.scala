package veritx.chipyard

import chisel3._
import chisel3.util._
import chisel3.stage.ChiselStage

/** Credit-controlled packet preview for one frozen compiled GEC contract.
  * The route table remains compiler supplied; this does not implement native
  * adaptive routing or claim cycle equivalence.
  */
class CompiledGecCreditPreviewIO(endpointCount: Int, flitWidth: Int) extends Bundle {
  val ingress = Vec(endpointCount, Flipped(Decoupled(UInt(flitWidth.W))))
  val egress = Vec(endpointCount, Decoupled(UInt(flitWidth.W)))
}

class CompiledGecCreditPreviewWithDiagnosticsIO(endpointCount: Int, flitWidth: Int,
    wireCount: Int, creditSlots: Int, inputSlots: Int, depth: Int)
    extends CompiledGecCreditPreviewIO(endpointCount, flitWidth) {
  val wireFire = Output(Vec(wireCount, Bool()))
  val freeCredits = Output(Vec(creditSlots, UInt(log2Ceil(depth + 1).W)))
  val ownedOutputVcs = Output(Vec(creditSlots, Bool()))
  val inputOccupancy = Output(Vec(inputSlots, UInt(log2Ceil(depth + 1).W)))
}

/** Structural facts about the frozen contract, shared by the elaborator and
  * the hierarchical emitter so the emitted bodies and the top cannot diverge.
  */
object CompiledGecCreditPreview {
  import SelectedGec._

  final case class LinkInput(resource: Int, tap: Int)

  private[chipyard] def localEndpointsOf: Seq[Seq[Int]] =
    (0 until routers).map(r => endpoints.indices.filter(endpoints(_) == r))

  private[chipyard] def outgoingOf: Seq[Seq[Int]] =
    (0 until routers).map(r => wires.indices.filter(wires(_)._1 == r))

  private[chipyard] def incomingOf: Seq[Seq[LinkInput]] =
    (0 until routers).map { r =>
      wires.indices.flatMap(w => wires(w)._2.indices.collect {
        case t if wires(w)._2(t) == r => LinkInput(w, t)
      })
    }

  /** One config per router.  Its distinct values are the router bodies the
    * hierarchical emitter writes once and the top instantiates many times:
    * the selected contract has two shapes (74 x 17-input, 7 x 16-input), not
    * 81, which is what makes the 81-router emit reachable. */
  def routerConfigs: Seq[CreditRouterConfig] = {
    val localEndpoints = localEndpointsOf
    val outgoing = outgoingOf
    val incoming = incomingOf
    val islip = vcAllocator == "islip"
    (0 until routers).map { r =>
      val portCount = localEndpoints(r).size + incoming(r).size
      val outputTaps = outgoing(r).map(w => wires(w)._2.size) ++ localEndpoints(r).map(_ => 1)
      require(portCount > 0 && outputTaps.nonEmpty)
      CreditRouterConfig(inputs = portCount, taps = outputTaps, vcs = vcs,
        width = width, depth = depth, outputDepth = outputStageDepth,
        iterations = allocatorIterations, islip = islip,
        waitForTailCredit = true, holdSwitch = holdSwitchForPacket,
        rcCycles = routeComputeCycles, vaCycles = vcAllocCycles,
        saCycles = switchAllocCycles, stCycles = switchTraversalCycles,
        outputCycles = outputDelayCycles, tagBits = 1)
    }
  }
}

/** Egress buffer with a stable module name.
  *
  * The router bodies are emitted as one separate circuit.  That circuit holds
  * a module called `Queue`; without this name the hierarchical top would emit
  * a second `Queue` with a different width and the two files could not be
  * compiled together.
  */
class GecEgressQueue(width: Int, depth: Int)
    extends Queue(UInt(width.W), depth, pipe = false, flow = false) {
  override def desiredName: String = "GecEgressQueue"
}

class CompiledGecCreditPreview(exposeDiagnostics: Boolean = true,
    hierarchical: Boolean = false) extends Module {
  import SelectedGec._
  require(routes.size == routers && routes.forall(_.size == routers))
  require(wireWidths.size == wires.size && wireLatencies.size == wires.size)
  require(wireWidths.forall(_ == width) && wireLatencies.forall(_ > 0))
  require(creditReturnLatency > 0)
  require(inputSpeedup == 1 && internalSpeedup == 1 && outputSpeedup == 1)
  require(inputBufferOrganization == "per_input_port_per_vc")
  require(inputVcPacketPolicy == "one_packet_at_a_time")
  require(vcAllocationScope == "packet" && vcReusePolicy == "wait_for_tail_credit")
  require(vcAllocator == switchAllocator && Set("islip", "round_robin")(vcAllocator))
  val islip = vcAllocator == "islip"
  require(wires.forall { case (src, taps) => src >= 0 && src < routers &&
    taps.nonEmpty && taps.forall(r => r >= 0 && r < routers) && taps.distinct.size == taps.size })

  import CompiledGecCreditPreview.LinkInput
  val localEndpoints = CompiledGecCreditPreview.localEndpointsOf
  val outgoing = CompiledGecCreditPreview.outgoingOf
  val incoming = CompiledGecCreditPreview.incomingOf
  require(localEndpoints.forall(xs => xs.distinct.size == xs.size))

  val configs = CompiledGecCreditPreview.routerConfigs

  val creditBase = configs.scanLeft(0)((base, cfg) => base + cfg.slots)
  val inputBase = configs.scanLeft(0)((base, cfg) => base + cfg.inputs * vcs)
  val totalCreditSlots = configs.map(_.slots).sum
  val totalInputSlots = configs.map(_.inputs * vcs).sum
  val io: CompiledGecCreditPreviewIO = IO(
    if (exposeDiagnostics)
      new CompiledGecCreditPreviewWithDiagnosticsIO(endpoints.size, width, wires.size,
        totalCreditSlots, totalInputSlots, depth)
    else new CompiledGecCreditPreviewIO(endpoints.size, width))
  private val diagnostics = if (exposeDiagnostics)
    Some(io.asInstanceOf[CompiledGecCreditPreviewWithDiagnosticsIO]) else None

  def source(f: UInt): UInt = f(sourceLsb + sourceWidth - 1, sourceLsb)
  def dest(f: UInt): UInt = f(destLsb + destWidth - 1, destLsb)
  def vc(f: UInt): UInt = f(vcLsb + vcWidth - 1, vcLsb)
  def flitType(f: UInt): UInt = f(typeLsb + typeWidth - 1, typeLsb)
  def isHead(f: UInt): Bool = flitType(f) === 0.U || flitType(f) === 3.U
  def isTail(f: UInt): Bool = flitType(f) === 2.U || flitType(f) === 3.U
  val vcMask = ((BigInt(1) << width) - 1) ^ (((BigInt(1) << vcWidth) - 1) << vcLsb)
  def withVc(f: UInt, value: UInt): UInt = (f & vcMask.U(width.W)) | (value << vcLsb)

  val routersById: Seq[CreditRouterLike] = (0 until routers).map { r =>
    if (hierarchical)
      Module(new CreditRouterExt(configs(r), CreditRouterEmit.moduleName(configs(r))))
    else
      Module(new CreditRouter(configs(r)))
  }
  for (r <- 0 until routers; p <- 0 until configs(r).inputs) {
    routersById(r).routerIo.in(p).valid := false.B
    routersById(r).routerIo.in(p).bits := 0.U.asTypeOf(new CreditPacketFlit(configs(r)))
  }
  for (r <- 0 until routers; s <- 0 until configs(r).slots) {
    routersById(r).routerIo.credit(s).valid := false.B
    routersById(r).routerIo.credit(s).bits.tail := false.B
  }

  val inputPortByLink = (0 until routers).map { r =>
    incoming(r).zipWithIndex.map { case (ref, port) => ref -> (localEndpoints(r).size + port) }.toMap
  }
  val egressQueues = endpoints.indices.map(_ => Module(new GecEgressQueue(width, depth)))

  for (r <- 0 until routers) {
    val router = routersById(r)
    val cfg = configs(r)
    for (s <- 0 until cfg.slots) {
      diagnostics.foreach { d =>
        d.freeCredits(creditBase(r) + s) := router.routerIo.free(s)
        d.ownedOutputVcs(creditBase(r) + s) := router.routerIo.occupied(s)
      }
    }
    for (p <- 0 until cfg.inputs; v <- 0 until vcs) {
      diagnostics.foreach { d =>
        d.inputOccupancy(inputBase(r) + p * vcs + v) := router.routerIo.inputOccupancy(p)(v)
      }
    }
    val localIn = localEndpoints(r)
    for ((endpoint, localPort) <- localIn.zipWithIndex) {
      val inputVc = vc(io.ingress(endpoint).bits)
      val validVc = inputVc < vcs.U
      val room = VecInit(router.routerIo.inputOccupancy(localPort).map(_ < depth.U))(inputVc)
      io.ingress(endpoint).ready := validVc && room
      router.routerIo.in(localPort).valid := io.ingress(endpoint).valid && io.ingress(endpoint).ready
      router.routerIo.in(localPort).bits.data := io.ingress(endpoint).bits
      router.routerIo.in(localPort).bits.vc := inputVc
      router.routerIo.in(localPort).bits.head := isHead(io.ingress(endpoint).bits)
      router.routerIo.in(localPort).bits.tail := isTail(io.ingress(endpoint).bits)
      router.routerIo.in(localPort).bits.tag := 0.U
      when(io.ingress(endpoint).valid) {
        SynthAssert(validVc, "ingress VC is outside the compiled GEC contract")
        SynthAssert(source(io.ingress(endpoint).bits) === endpoint.U,
          "source endpoint does not match its trusted ingress port")
        SynthAssert(dest(io.ingress(endpoint).bits) < endpoints.size.U,
          "ingress destination is outside the compiled GEC contract")
      }
    }

    val routeSlotByDestination = endpoints.indices.map { endpoint =>
      val destinationRouter = endpoints(endpoint)
      val (resource, next, routeVc) = routes(r)(destinationRouter)
      require(routeVc >= 0 && routeVc < vcs, s"route VC out of range at router $r to endpoint $endpoint")
      if (resource == -1) {
        require(next == r && endpoints(endpoint) == r,
          s"local route at router $r does not terminate at endpoint $endpoint")
        val localOut = localEndpoints(r).indexOf(endpoint)
        require(localOut >= 0, s"router $r lacks local egress endpoint $endpoint")
        val output = outgoing(r).size + localOut
        configs(r).taps.take(output).sum * vcs + routeVc
      } else {
        require(resource >= 0 && resource < wires.size && wires(resource)._1 == r,
          s"route at router $r names a non-local GEC wire $resource")
        val output = outgoing(r).indexOf(resource)
        val tap = wires(resource)._2.indexOf(next)
        require(output >= 0 && tap >= 0,
          s"route at router $r names a missing tap $next on wire $resource")
        configs(r).taps.take(output).sum * vcs + tap * vcs + routeVc
      }
    }
    val routeSlots = VecInit(routeSlotByDestination.map(_.U(cfg.slotBits.W)))
    for (lane <- 0 until cfg.lanes) {
      val head = router.routerIo.routeHead(lane)
      val endpoint = dest(head.bits.data)
      val validEndpoint = endpoint < endpoints.size.U
      val selectedSlot = routeSlots(endpoint)
      // The route is a slot index plus that slot's tag.  The compiled
      // contract resolves every destination to exactly one slot per VC.
      router.routerIo.route(lane).slot := selectedSlot
      router.routerIo.route(lane).valid := head.valid && validEndpoint
      router.routerIo.route(lane).tag := 0.U(cfg.tagBits.W)
      when(head.valid) {
        SynthAssert(validEndpoint, "route head destination is outside the compiled GEC contract")
      }
    }

    for ((endpoint, localOut) <- localEndpoints(r).zipWithIndex) {
      val output = outgoing(r).size + localOut
      val queue = egressQueues(endpoint)
      val packet = router.routerIo.out(output).bits.flit
      queue.io.enq.valid := router.routerIo.out(output).valid
      queue.io.enq.bits := withVc(packet.data, packet.vc)
      when(router.routerIo.out(output).valid) {
        SynthAssert(queue.io.enq.ready, "egress credit exceeded its queue capacity")
      }
      io.egress(endpoint) <> queue.io.deq
      val slotBase = cfg.taps.take(output).sum * vcs
      for (v <- 0 until vcs) {
        router.routerIo.credit(slotBase + v).valid := queue.io.deq.fire &&
          queue.io.deq.bits(vcLsb + vcWidth - 1, vcLsb) === v.U
        router.routerIo.credit(slotBase + v).bits.tail := isTail(queue.io.deq.bits)
      }
    }
  }

  for (resource <- wires.indices) {
    val (source, taps) = wires(resource)
    val sourceOutput = outgoing(source).indexOf(resource)
    require(sourceOutput >= 0)
    val sourceRouter = routersById(source)
    val sourceCfg = configs(source)
    val output = sourceRouter.routerIo.out(sourceOutput)
    val packet = Wire(new CreditRouterOutput(sourceCfg))
    packet := output.bits
    packet.flit.data := withVc(output.bits.flit.data, output.bits.flit.vc)
    val latency = wireLatencies(resource)
    val delayedValid = ShiftRegister(output.valid, latency, false.B, true.B)
    val delayedPacket = ShiftRegister(packet, latency)
    diagnostics.foreach(_.wireFire(resource) := delayedValid)

    for ((destination, tap) <- taps.zipWithIndex) {
      val inputPort = inputPortByLink(destination)(LinkInput(resource, tap))
      val receiver = routersById(destination)
      val receiverInput = receiver.routerIo.in(inputPort)
      receiverInput.valid := delayedValid && delayedPacket.tap === tap.U
      receiverInput.bits.data := delayedPacket.flit.data
      receiverInput.bits.vc := delayedPacket.flit.vc
      receiverInput.bits.head := isHead(delayedPacket.flit.data)
      receiverInput.bits.tail := isTail(delayedPacket.flit.data)
      receiverInput.bits.tag := delayedPacket.flit.tag

      val tapSlotBase = sourceCfg.taps.take(sourceOutput).sum * vcs + tap * vcs
      for (v <- 0 until vcs) {
        val returned = receiver.routerIo.returned(inputPort)(v)
        val creditValid = ShiftRegister(returned.valid, creditReturnLatency, false.B, true.B)
        val creditBits = ShiftRegister(returned.bits, creditReturnLatency)
        sourceRouter.routerIo.credit(tapSlotBase + v).valid := creditValid
        sourceRouter.routerIo.credit(tapSlotBase + v).bits := creditBits
      }
    }
  }
}

object EmitCompiledGecCreditPreview extends App {
  require(args.length == 1, "output directory required")
  val inputPorts = (0 until SelectedGec.routers).map { router =>
    SelectedGec.endpoints.count(_ == router) +
      SelectedGec.wires.map(_._2.count(_ == router)).sum
  }
  val outputSlots = (0 until SelectedGec.routers).map { router =>
    SelectedGec.wires.filter(_._1 == router).map(_._2.size).sum +
      SelectedGec.endpoints.count(_ == router)
  }
  val flitBundleBits = SelectedGec.width + math.max(1, log2Ceil(SelectedGec.vcs)) + 3
  val inputStorageBits = inputPorts.map(_ * SelectedGec.vcs * SelectedGec.depth * flitBundleBits).sum
  val outputStorageBits = outputSlots.map(_ * SelectedGec.vcs * SelectedGec.outputStageDepth * flitBundleBits).sum
  val egressStorageBits = SelectedGec.endpoints.size * SelectedGec.depth * SelectedGec.width
  println(s"ELABORATION credit GEC routers=${SelectedGec.routers} endpoints=${SelectedGec.endpoints.size} vcs=${SelectedGec.vcs} shared_wires=${SelectedGec.wires.size} input_ports=${inputPorts.sum} max_inputs=${inputPorts.max} output_vc_slots=${outputSlots.sum * SelectedGec.vcs} max_output_vc_slots=${outputSlots.max * SelectedGec.vcs} estimated_queue_bits=${inputStorageBits + outputStorageBits + egressStorageBits}")

  // Emit one router body per distinct shape before the top.  Chisel builds a
  // module per instance, so instantiating CreditRouter 81 times would put 81
  // bodies in the FIRRTL IR; at the selected shape that is ~1.4 GB and exhausts
  // the heap.  The top then instantiates these pre-emitted bodies as
  // black boxes, and firtool keeps one module name per shape.
  val configs = CompiledGecCreditPreview.routerConfigs
  val shapes = configs.distinct
  println(s"HIERARCHY routers=${configs.size} distinct_shapes=${shapes.size} " +
    shapes.groupBy(identity).map { case (c, cs) => s"${c.inputs}x${c.taps.size}/${c.vcs}vc=x${cs.size}" }.mkString(" ", " ", ""))
  val bodyNames = CreditRouterEmit.emitBodies(shapes, args(0))
  shapes.zip(bodyNames).foreach { case (c, name) =>
    println(s"EMITTED router body name=$name inputs=${c.inputs} taps=${c.taps.size} vcs=${c.vcs} slots=${c.slots} lanes=${c.lanes}")
  }

  val previous = Option(System.getProperty("veritx.synthesize"))
  System.setProperty("veritx.synthesize", "1")
  try {
    (new ChiselStage).emitVerilog(new CompiledGecCreditPreview(exposeDiagnostics = false,
        hierarchical = true),
      Array("--target-dir", args(0)))
  } finally {
    previous match {
      case Some(value) => System.setProperty("veritx.synthesize", value)
      case None => System.clearProperty("veritx.synthesize")
    }
  }
  println(s"EMITTED credit GEC contract=${SelectedGec.contractHash} routers=${SelectedGec.routers} vcs=${SelectedGec.vcs} shared_wires=${SelectedGec.wires.size} distinct_router_bodies=${shapes.size}")
}
