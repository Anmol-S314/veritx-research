package veritx.chipyard

import chisel3._
import chisel3.util._

final case class CreditRouterConfig(inputs: Int, taps: Seq[Int], vcs: Int,
    width: Int = 128, depth: Int = 8, outputDepth: Int = 1,
    iterations: Int = 1, islip: Boolean = true, waitForTailCredit: Boolean = true,
    holdSwitch: Boolean = false, rcCycles: Int = 0, vaCycles: Int = 1,
    saCycles: Int = 1, stCycles: Int = 1, outputCycles: Int = 0,
    tagBits: Int = 32) {
  require(inputs > 0 && taps.nonEmpty && taps.forall(_ > 0) && vcs > 0)
  require(width > 0 && depth > 0 && outputDepth > 0 && iterations > 0 && tagBits > 0)
  require(Seq(rcCycles, vaCycles, saCycles, stCycles, outputCycles).forall(_ >= 0))
  val outputs = taps.size
  val slots = taps.sum * vcs
  val lanes = inputs * vcs
  val vcBits = math.max(1, log2Ceil(vcs))
  val slotBits = math.max(1, log2Ceil(slots))
  val slotOutput = taps.indices.flatMap(o => Seq.fill(taps(o)*vcs)(o)).toSeq
  val slotTap = taps.flatMap(t => (0 until t).flatMap(i => Seq.fill(vcs)(i)))
  val slotVc = taps.flatMap(t => (0 until t).flatMap(_ => 0 until vcs))
}
class CreditPacketFlit(c: CreditRouterConfig) extends Bundle {
  val data = UInt(c.width.W)
  val vc = UInt(c.vcBits.W)
  val head = Bool()
  val tail = Bool()
  val tag = UInt(c.tagBits.W)
}
class CreditPulse extends Bundle { val tail = Bool() }
/** The route a lane's head flit resolves to.

  The compiled contract resolves every destination to exactly one credit slot
  per VC, so a route is a slot *index* plus that slot's tag, not a one-hot
  mask over every slot.  The one-hot form carried 2,966,784 bits across the
  router boundary and drove 2,998,768 FIRRTL reduction nodes at the selected
  81-router shape, which is what exhausted the elaborator's heap; this form
  carries 97,744 bits and 374,846 nodes.  `valid` reports that the head
  resolves to a slot at all, which the one-hot form expressed as an all-zero
  mask.
*/
class CreditRoute(c: CreditRouterConfig) extends Bundle {
  val slot = UInt(c.slotBits.W)
  val valid = Bool()
  val tag = UInt(c.tagBits.W)
}
class CreditRouterOutput(c: CreditRouterConfig) extends Bundle {
  val flit = new CreditPacketFlit(c)
  val tap = UInt(math.max(1, log2Ceil(c.taps.max)).W)
}

/** The port set of one credit router.
  *
  * It is a named bundle so the same ports can be used by the elaborated
  * `CreditRouter` and by the black-box view of a pre-emitted router body.
  */
class CreditRouterIO(c: CreditRouterConfig) extends Bundle {
  val in = Flipped(Vec(c.inputs, Valid(new CreditPacketFlit(c))))
  val returned = Output(Vec(c.inputs, Vec(c.vcs, Valid(new CreditPulse))))
  val routeHead = Output(Vec(c.lanes, Valid(new CreditPacketFlit(c))))
  val route = Input(Vec(c.lanes, new CreditRoute(c)))
  val out = Vec(c.outputs, Valid(new CreditRouterOutput(c)))
  val credit = Flipped(Vec(c.slots, Valid(new CreditPulse)))
  val free = Output(Vec(c.slots, UInt(log2Ceil(c.depth+1).W)))
  val occupied = Output(Vec(c.slots, Bool()))
  val inputOccupancy = Output(Vec(c.inputs, Vec(c.vcs, UInt(log2Ceil(c.depth+1).W))))
}

trait CreditRouterLike { def routerIo: CreditRouterIO }

/** Grant/accept matching. iSLIP advances pointers on committed iteration-zero
  * matches only; round-robin advances on every committed match.
  */
class CreditMatch(inputs: Int, outputs: Int, iterations: Int, islip: Boolean) extends Module {
  require(inputs > 0 && outputs > 0 && iterations > 0)
  val io = IO(new Bundle {
    val request = Input(Vec(inputs, UInt(outputs.W)))
    val matched = Output(Vec(inputs, UInt(outputs.W)))
    val commit = Input(Vec(inputs, UInt(outputs.W)))
  })
  val grantPtr = RegInit(VecInit(Seq.fill(outputs)(0.U(math.max(1, log2Ceil(inputs)).W))))
  val acceptPtr = RegInit(VecInit(Seq.fill(inputs)(0.U(math.max(1, log2Ceil(outputs)).W))))
  def pick(request: UInt, start: UInt, size: Int): UInt = {
    val rotated = (Cat(request, request) >> start)(size-1, 0)
    val sum = PriorityEncoder(rotated) +& start
    val index = Mux(sum >= size.U, sum - size.U, sum)
    Mux(request.orR, UIntToOH(index, size), 0.U(size.W))
  }
  var rows = Seq.fill(inputs)(0.U(outputs.W))
  var usedInputs = 0.U(inputs.W)
  var usedOutputs = 0.U(outputs.W)
  var first = Seq.fill(inputs)(0.U(outputs.W))
  for (iteration <- 0 until iterations) {
    // The "already used" factors depend on the input or on the output, not on
    // the pair, so they are hoisted out of the pair loop.  That is the
    // difference between three nodes per (input, output) pair and seven, and
    // this pair matrix is the largest single term in the elaborated design.
    val freeInputs = ~usedInputs
    val freeOutputs = ~usedOutputs
    val grants = (0 until outputs).map { o =>
      val requests = VecInit((0 until inputs).map(i =>
        io.request(i)(o) && freeInputs(i))).asUInt & Fill(inputs, freeOutputs(o))
      pick(requests, grantPtr(o), inputs)
    }
    val accepts = (0 until inputs).map { i =>
      pick(VecInit((0 until outputs).map(o => grants(o)(i))).asUInt, acceptPtr(i), outputs)
    }
    if (iteration == 0) first = accepts
    rows = rows.zip(accepts).map { case (a, b) => a | b }
    usedInputs = usedInputs | VecInit(accepts.map(_.orR)).asUInt
    usedOutputs = usedOutputs | accepts.reduce(_ | _)
  }
  for (i <- 0 until inputs) {
    io.matched(i) := rows(i)
    SynthAssert(PopCount(rows(i)) <= 1.U)
    SynthAssert((io.commit(i) & ~rows(i)) === 0.U, "unmatched allocation was committed")
    val advance = io.commit(i) & (if (islip) first(i) else rows(i))
    when(advance.orR) {
      val o = OHToUInt(advance)
      acceptPtr(i) := Mux(o === (outputs-1).U, 0.U, o + 1.U)
    }
  }
  for (o <- 0 until outputs) {
    SynthAssert(PopCount(VecInit(rows.map(_(o))).asUInt) <= 1.U)
    val commits = VecInit((0 until inputs).map(i =>
      io.commit(i)(o) && (if (islip) first(i)(o) else rows(i)(o)))).asUInt
    when(commits.orR) {
      val i = OHToUInt(commits)
      grantPtr(o) := Mux(i === (inputs-1).U, 0.U, i + 1.U)
    }
  }
}

/** Credits count downstream input-buffer slots, including in-flight flits.
  * VC ownership is separate and cannot be released by an ordinary body credit.
  */
class CreditOwnership(slots: Int, depth: Int, waitTail: Boolean) extends Module {
  val io = IO(new Bundle {
    val reserve = Input(Vec(slots, Bool()))
    val send = Input(Vec(slots, Bool()))
    val sendTail = Input(Vec(slots, Bool()))
    val returned = Input(Vec(slots, Valid(new CreditPulse)))
    val free = Output(Vec(slots, UInt(log2Ceil(depth+1).W)))
    val occupied = Output(Vec(slots, Bool()))
    val waitingTail = Output(Vec(slots, Bool()))
  })
  val free = RegInit(VecInit(Seq.fill(slots)(depth.U(log2Ceil(depth+1).W))))
  val occupied = RegInit(VecInit(Seq.fill(slots)(false.B)))
  val tailPending = RegInit(VecInit(Seq.fill(slots)(false.B)))
  for (s <- 0 until slots) {
    io.free(s) := free(s); io.occupied(s) := occupied(s); io.waitingTail(s) := tailPending(s)
    val returned = io.returned(s).valid
    when(io.send(s)) {
      SynthAssert(free(s) =/= 0.U, "credit underflow")
      SynthAssert(occupied(s) || io.reserve(s), "flit sent on an unowned output VC")
    }
    when(returned) { SynthAssert(free(s) < depth.U || io.send(s), "duplicate credit/overflow") }
    when(io.send(s) =/= returned) { free(s) := Mux(returned, free(s)+1.U, free(s)-1.U) }
    when(io.reserve(s)) {
      SynthAssert(!occupied(s), "output VC allocated twice")
      occupied(s) := true.B
    }
    if (waitTail) {
      when(io.sendTail(s)) { SynthAssert(io.send(s)); tailPending(s) := true.B }
      when(returned && io.returned(s).bits.tail) {
        SynthAssert(tailPending(s) || io.sendTail(s), "tail credit has no matching packet")
        occupied(s) := false.B; tailPending(s) := false.B
      }
    } else {
      when(io.sendTail(s)) { SynthAssert(io.send(s)); occupied(s) := false.B }
    }
  }
}

/** Credit-controlled wormhole router, with independent per-input/per-VC FIFOs,
  * packet-scoped output-VC reservation, grant/accept VA and SA, staged traversal,
  * output buffering, and explicit return-credit/tail tokens.
  * The route engine supplies native legal masks; BODY/TAIL never recompute RC.
  */
class CreditRouter(c: CreditRouterConfig) extends Module with CreditRouterLike {
  val io = IO(new CreditRouterIO(c))
  def routerIo: CreditRouterIO = io
  val credits = Module(new CreditOwnership(c.slots, c.depth, c.waitForTailCredit))
  credits.io.returned := io.credit
  io.free := credits.io.free; io.occupied := credits.io.occupied
  credits.io.reserve.foreach(_ := false.B)
  credits.io.send.foreach(_ := false.B)
  credits.io.sendTail.foreach(_ := false.B)
  val fifo = (0 until c.lanes).map { lane =>
    val p = lane / c.vcs; val v = lane % c.vcs
    val q = Module(new Queue(new CreditPacketFlit(c), c.depth, pipe = false, flow = false))
    q.io.enq.valid := io.in(p).valid && io.in(p).bits.vc === v.U
    q.io.enq.bits := io.in(p).bits
    q.io.deq.ready := false.B
    io.inputOccupancy(p)(v) := q.io.count
    io.returned(p)(v).valid := q.io.deq.fire
    io.returned(p)(v).bits.tail := q.io.deq.bits.tail
    val packetOpen = RegInit(false.B)
    when(q.io.enq.valid) {
      SynthAssert(q.io.enq.ready, "upstream violated the credit contract")
      when(q.io.enq.bits.head) { SynthAssert(!packetOpen, "HEAD before previous TAIL") }
        .otherwise { SynthAssert(packetOpen, "BODY/TAIL without HEAD") }
      packetOpen := !q.io.enq.bits.tail
    }
    q
  }
  for (p <- 0 until c.inputs) { when(io.in(p).valid) { SynthAssert(io.in(p).bits.vc < c.vcs.U) } }
  val active = RegInit(VecInit(Seq.fill(c.lanes)(false.B)))
  val selected = Reg(Vec(c.lanes, UInt(c.slotBits.W)))
  val selectedTag = Reg(Vec(c.lanes, UInt(c.tagBits.W)))
  val vaWait = RegInit(VecInit(Seq.fill(c.lanes)(0.U(math.max(1, log2Ceil(c.vaCycles+1)).W))))
  val routeReady = Wire(Vec(c.lanes, Bool()))
  val legalSlot = Wire(Vec(c.lanes, UInt(c.slotBits.W)))
  val legalTag = Wire(Vec(c.lanes, UInt(c.tagBits.W)))
  val legalOk = Wire(Vec(c.lanes, Bool()))
  for (l <- 0 until c.lanes) {
    io.routeHead(l).valid := fifo(l).io.deq.valid && !active(l)
    io.routeHead(l).bits := fifo(l).io.deq.bits
    when(io.routeHead(l).valid) { SynthAssert(fifo(l).io.deq.bits.head, "packet lost its reservation") }
    when(vaWait(l) =/= 0.U) { vaWait(l) := vaWait(l)-1.U }
    if (c.rcCycles == 0) {
      routeReady(l) := io.routeHead(l).valid
      legalSlot(l) := io.route(l).slot; legalOk(l) := io.route(l).valid
      legalTag(l) := io.route(l).tag
    } else {
      val captured = RegInit(false.B)
      val delay = RegInit(0.U(math.max(1, log2Ceil(c.rcCycles)).W))
      val held = Reg(new CreditRoute(c))
      when(io.routeHead(l).valid && !captured) {
        held := io.route(l); delay := (c.rcCycles-1).U; captured := true.B
      }
      when(delay =/= 0.U) { delay := delay-1.U }
      when(fifo(l).io.deq.fire && fifo(l).io.deq.bits.tail) { captured := false.B }
      routeReady(l) := captured && delay === 0.U && io.routeHead(l).valid
      legalSlot(l) := held.slot; legalOk(l) := held.valid; legalTag(l) := held.tag
    }
  }
  // Select one pending input VC per physical input before VC matching.
  val vaLane = Wire(Vec(c.inputs, UInt(math.max(1, log2Ceil(c.vcs)).W)))
  val va = Module(new CreditMatch(c.inputs, c.slots, c.iterations, c.islip))
  val vaRotate = RegInit(VecInit(Seq.fill(c.inputs)(0.U(math.max(1, log2Ceil(c.vcs)).W))))
  val freeSlots = VecInit(credits.io.occupied.map(!_)).asUInt
  // A single-slot router has no dynamic index to resolve, so the extract is
  // constant; this keeps the index width from exceeding the extractee width.
  def slotFree(idx: UInt): Bool =
    if (c.slots == 1) !credits.io.occupied(0) else freeSlots(idx)
  val laneGrant = Wire(Vec(c.lanes, UInt(c.slots.W)))
  laneGrant.foreach(_ := 0.U)
  for (p <- 0 until c.inputs) {
    val candidates = VecInit((0 until c.vcs).map { v =>
      val l = p*c.vcs+v
      // The legal slot is read out of the free mask by index, so a lane costs
      // one indexed read instead of a slots-wide mask compare.
      val idx = Mux(legalOk(l) && legalSlot(l) < c.slots.U, legalSlot(l), 0.U)
      routeReady(l) && legalOk(l) && slotFree(idx)
    }).asUInt
    val rotated = (Cat(candidates, candidates) >> vaRotate(p))(c.vcs-1, 0)
    val sum = PriorityEncoder(rotated) +& vaRotate(p)
    vaLane(p) := Mux(sum >= c.vcs.U, sum-c.vcs.U, sum)
    // The allocator request is decoded once per input port rather than once
    // per lane.  The winning VC's lane supplies the slot.
    val chosenSlot = VecInit((0 until c.vcs).map(v => legalSlot(p*c.vcs+v)))(vaLane(p))
    val requestSlot = Mux(chosenSlot < c.slots.U, chosenSlot, 0.U)
    va.io.request(p) := Mux(candidates.orR,
      UIntToOH(requestSlot, c.slots) & freeSlots, 0.U)
    va.io.commit(p) := va.io.matched(p)
    when(va.io.matched(p).orR) {
      vaRotate(p) := Mux(vaLane(p) === (c.vcs-1).U, 0.U, vaLane(p)+1.U)
    }
    for (v <- 0 until c.vcs) {
      val l = p*c.vcs+v
      when(vaLane(p) === v.U && va.io.matched(p).orR) {
        laneGrant(l) := va.io.matched(p)
        selected(l) := OHToUInt(va.io.matched(p))
        // The granted slot is the lane's legal slot, so the tag carried with
        // the grant is the legal slot's tag, captured at grant time.
        selectedTag(l) := legalTag(l)
        active(l) := true.B
        vaWait(l) := math.max(0, c.vaCycles-1).U
      }
    }
  }
  // A credit slot is reserved by the VC allocator for at most one lane per
  // input port, so the reservation reduces over input ports rather than over
  // every lane.  That is the same set of grants at a fraction of the logic.
  for (s <- 0 until c.slots) {
    credits.io.reserve(s) := VecInit(va.io.matched.map(_(s))).asUInt.orR
  }
  val slot = (0 until c.lanes).map(l =>
    Mux(active(l), selected(l), OHToUInt(laneGrant(l))))
  // The tag travels with the grant: it is captured when the slot is granted,
  // so it is the tag of the slot that was granted rather than a re-read of a
  // per-slot vector at send time.
  val tag = (0 until c.lanes).map(l => selectedTag(l))
  val canSend = (0 until c.lanes).map(l =>
    fifo(l).io.deq.valid && ((active(l) && vaWait(l) === 0.U) ||
      (if (c.vaCycles == 0) laneGrant(l).orR else false.B)))

  // A separate output-stage queue exists for each (physical output,tap,VC).
  // Its slots are reserved at SA, before fixed traversal latency elapses.
  val staged = (0 until c.slots).map(_ => Module(new Queue(new CreditPacketFlit(c), c.outputDepth)))
  val stageFree = RegInit(VecInit(Seq.fill(c.slots)(c.outputDepth.U(log2Ceil(c.outputDepth+1).W))))
  val reserveStage = Wire(Vec(c.slots, Bool()))
  val sa = Module(new CreditMatch(c.inputs, c.outputs, c.iterations, c.islip))
  val saLane = Wire(Vec(c.inputs, UInt(math.max(1, log2Ceil(c.vcs)).W)))
  val saPtr = RegInit(VecInit(Seq.fill(c.inputs)(0.U(math.max(1, log2Ceil(c.vcs)).W))))
  val locked = RegInit(VecInit(Seq.fill(c.outputs)(false.B)))
  val lockLane = Reg(Vec(c.outputs, UInt(math.max(1, log2Ceil(c.lanes)).W)))
  val slotOutput = VecInit(c.slotOutput.map(_.U))
  for (p <- 0 until c.inputs) {
    val candidates = VecInit((0 until c.vcs).map { v =>
      val l = p*c.vcs+v
      val o = slotOutput(slot(l))
      canSend(l) && stageFree(slot(l)) =/= 0.U && (!locked(o) || lockLane(o) === l.U)
    }).asUInt
    val rotated = (Cat(candidates, candidates) >> saPtr(p))(c.vcs-1, 0)
    val sum = PriorityEncoder(rotated) +& saPtr(p)
    saLane(p) := Mux(sum >= c.vcs.U, sum-c.vcs.U, sum)
    val outputs = VecInit((0 until c.vcs).map(v => slotOutput(slot(p*c.vcs+v))))
    sa.io.request(p) := Mux(candidates.orR, UIntToOH(outputs(saLane(p)), c.outputs), 0.U)
    sa.io.commit(p) := sa.io.matched(p)
    when(sa.io.matched(p).orR) { saPtr(p) := Mux(saLane(p) === (c.vcs-1).U, 0.U, saLane(p)+1.U) }
  }
  val arrivals = Wire(Vec(c.slots, Valid(new CreditPacketFlit(c))))
  arrivals.foreach { a => a.valid := false.B; a.bits := 0.U.asTypeOf(new CreditPacketFlit(c)) }
  val launchStage = Wire(Vec(c.outputs, Valid(new Bundle {
    val flit = new CreditPacketFlit(c)
    val slot = UInt(c.slotBits.W)
  })))
  val laneFire = Wire(Vec(c.lanes, Bool()))
  val laneSlot = Wire(Vec(c.lanes, UInt(c.slotBits.W)))
  val slotVcLookup = VecInit(c.slotVc.map(_.U(c.vcBits.W)))
  // The switch allocator grants at most one lane per input port, so the
  // fired slot and payload are carried per input port rather than per lane.
  // That removes a per-lane one-hot over every slot.
  val firedSlot = WireDefault(VecInit(Seq.fill(c.inputs)(0.U(c.slotBits.W))))
  val firedPayload = WireDefault(VecInit(Seq.fill(c.inputs)(0.U.asTypeOf(new CreditPacketFlit(c)))))
  val firedByInput = WireDefault(VecInit(Seq.fill(c.inputs)(false.B)))
  for (p <- 0 until c.inputs; v <- 0 until c.vcs) {
    val l = p*c.vcs+v
    val fire = sa.io.matched(p).orR && saLane(p) === v.U
    laneFire(l) := fire
    laneSlot(l) := slot(l)
    val payload = Wire(new CreditPacketFlit(c))
    payload := fifo(l).io.deq.bits
    payload.vc := slotVcLookup(slot(l)); payload.tag := tag(l)
    when(fire) {
      firedSlot(p) := laneSlot(l)
      firedPayload(p) := payload
      firedByInput(p) := true.B
    }
    fifo(l).io.deq.ready := fire
    when(fire && fifo(l).io.deq.bits.tail) { active(l) := false.B }
    if (c.holdSwitch) {
      val o = slotOutput(slot(l))
      when(fire) {
        locked(o) := !fifo(l).io.deq.bits.tail
        lockLane(o) := l.U
      }
    }
  }
  for (s <- 0 until c.slots) {
    reserveStage(s) := VecInit(firedSlot.map(sl =>
      firedByInput(sl) && sl === s.U)).asUInt.orR
  }
  for (o <- 0 until c.outputs) {
    val selectedInputs = VecInit((0 until c.inputs).map(p =>
      firedByInput(p) && slotOutput(firedSlot(p)) === o.U)).asUInt
    SynthAssert(PopCount(selectedInputs) <= 1.U, "switch allocator granted one output to multiple lanes")
    launchStage(o).valid := selectedInputs.orR
    launchStage(o).bits.flit := Mux1H(selectedInputs, firedPayload)
    launchStage(o).bits.slot := Mux1H(selectedInputs, firedSlot)
  }
  for (o <- 0 until c.outputs) {
    val delay = c.saCycles+c.stCycles
    val valid = if (delay == 0) launchStage(o).valid else ShiftRegister(launchStage(o).valid, delay, false.B, true.B)
    val data = if (delay == 0) launchStage(o).bits else ShiftRegister(launchStage(o).bits, delay)
    for (s <- 0 until c.slots if c.slotOutput(s) == o) {
      when(valid && data.slot === s.U) { arrivals(s).valid := true.B; arrivals(s).bits := data.flit }
    }
  }
  for (s <- 0 until c.slots) {
    staged(s).io.enq.valid := arrivals(s).valid; staged(s).io.enq.bits := arrivals(s).bits
    staged(s).io.deq.ready := false.B
    when(arrivals(s).valid) { SynthAssert(staged(s).io.enq.ready, "unreserved output-stage arrival") }
    when(reserveStage(s) =/= staged(s).io.deq.fire) {
      stageFree(s) := Mux(staged(s).io.deq.fire, stageFree(s)+1.U, stageFree(s)-1.U)
    }
    when(reserveStage(s)) { SynthAssert(stageFree(s) =/= 0.U) }
  }
  for (o <- 0 until c.outputs) {
    val slots = (0 until c.slots).filter(c.slotOutput(_) == o)
    val arb = Module(new RRArbiter(new CreditPacketFlit(c), slots.size))
    for ((s, i) <- slots.zipWithIndex) {
      arb.io.in(i).valid := staged(s).io.deq.valid && credits.io.free(s) =/= 0.U
      arb.io.in(i).bits := staged(s).io.deq.bits
      staged(s).io.deq.ready := arb.io.in(i).ready && credits.io.free(s) =/= 0.U
      credits.io.send(s) := staged(s).io.deq.fire
      credits.io.sendTail(s) := staged(s).io.deq.fire && staged(s).io.deq.bits.tail
    }
    arb.io.out.ready := true.B
    val tap = VecInit(slots.map(s => c.slotTap(s).U))(arb.io.chosen)
    val valid = arb.io.out.valid
    if (c.outputCycles == 0) {
      io.out(o).valid := valid; io.out(o).bits.flit := arb.io.out.bits; io.out(o).bits.tap := tap
    } else {
      io.out(o).valid := ShiftRegister(valid, c.outputCycles, false.B, true.B)
      io.out(o).bits.flit := ShiftRegister(arb.io.out.bits, c.outputCycles)
      io.out(o).bits.tap := ShiftRegister(tap, c.outputCycles)
    }
  }
}
