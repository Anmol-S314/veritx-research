package veritx.chipyard

import chisel3._
import chisel3.util._

/** Exact native GEC cost rule over real free-credit counters. The observation
  * mask is separate from the legal/free allocation mask: occupied VCs still
  * contribute to GetUsedCredit(port[,drop]). Ties select express.
  */
class HybridRoutePolicy(slots: Int, depth: Int, distanceBits: Int, tagBits: Int = 32) extends Module {
  require(slots > 0 && depth > 0 && distanceBits > 0)
  val io = IO(new Bundle {
    val meshLegal = Input(UInt(slots.W))
    val expressLegal = Input(UInt(slots.W))
    val meshObserve = Input(UInt(slots.W))
    val expressObserve = Input(UInt(slots.W))
    val free = Input(Vec(slots, UInt(log2Ceil(depth+1).W)))
    val meshHops = Input(UInt(distanceBits.W))
    val meshTag = Input(UInt(tagBits.W))
    val expressTag = Input(UInt(tagBits.W))
    val legal = Output(UInt(slots.W))
    val tag = Output(UInt(tagBits.W))
    val meshSelected = Output(Bool())
  })
  val meshUsed = (0 until slots).map(s =>
    Mux(io.meshObserve(s), depth.U - io.free(s), 0.U)).reduce(_ +& _)
  val expressUsed = (0 until slots).map(s =>
    Mux(io.expressObserve(s), depth.U - io.free(s), 0.U)).reduce(_ +& _)
  val meshCost = meshUsed * io.meshHops
  val takeMesh = io.meshLegal.orR && (!io.expressLegal.orR || meshCost < expressUsed)
  io.meshSelected := takeMesh
  io.legal := Mux(takeMesh, io.meshLegal, io.expressLegal)
  io.tag := Mux(takeMesh, io.meshTag, io.expressTag)
  for (s <- 0 until slots) { SynthAssert(io.free(s) <= depth.U) }
  when(io.meshLegal.orR) { SynthAssert(io.meshHops =/= 0.U) }
}

final case class SrotaFiuConfig(k: Int, sources: Int, concentration: Int = 1,
    entries: Int = 64, epochCycles: Int = 1024, paths: Int = 3,
    threshold: Int = 8, oneShapePerEpoch: Boolean = false,
    islandColumns: Set[Int] = Set.empty, forcedShape: Int = -1) {
  require(k >= 2 && sources > 0 && concentration > 0 && entries > 0 && epochCycles > 0)
  require(paths > 0 && paths < 8 && threshold >= 0 && threshold <= 15)
  require(islandColumns.forall(x => x >= 0 && x < k))
  require(islandColumns.isEmpty || (paths & 2) != 0)
  require(forcedShape >= -1 && forcedShape <= 2)
  require(forcedShape < 0 || (paths & (1 << forcedShape)) != 0)
}
class SrotaFlow(c: SrotaFiuConfig) extends Bundle {
  val source = UInt(16.W)
  val destination = UInt(16.W)
  val trafficClass = UInt(8.W)
}
class SrotaDecision(c: SrotaFiuConfig) extends Bundle {
  val shape = UInt(2.W)
  val intermediate = UInt(math.max(1, log2Ceil(c.k*c.k)).W)
  val epoch = UInt(64.W)
  val flowHash = UInt(16.W)
  val cacheHit = Bool()
}

/** Flow/epoch cache and shape/intermediate selection behind a two-channel
  * interface. The RNG word is injected so differential tests can replay the
  * native simulator's random stream rather than assume an identical RNG.
  */
class SrotaInjectionPolicy(c: SrotaFiuConfig) extends Module {
  val io = IO(new Bundle {
    val flow = Flipped(Decoupled(new SrotaFlow(c)))
    val decision = Decoupled(new SrotaDecision(c))
    val rowLoads = Input(Vec(c.k, UInt(4.W)))
    val columnLoads = Input(Vec(c.k, UInt(4.W)))
    val randomWord = Input(UInt(32.W))
    val randomUsed = Output(Bool())
  })
  val cycle = RegInit(0.U(64.W)); cycle := cycle+1.U
  val epoch = cycle / c.epochCycles.U
  // Native hash arithmetic wraps at 32 bits before the final 16-bit fold.
  val a = (io.flow.bits.source * "h9e3779b1".U(32.W))(31, 0)
  val b = (io.flow.bits.destination * 40503.U(32.W))(31, 0)
  val d = (io.flow.bits.trafficClass * "h85ebca77".U(32.W))(31, 0)
  val mix = a ^ b ^ d
  val hash = (mix ^ (mix >> 16))(15, 0)
  val index = hash % c.entries.U
  val valid = Seq.fill(c.sources)(RegInit(VecInit(Seq.fill(c.entries)(false.B))))
  val epochs = Seq.fill(c.sources)(Reg(Vec(c.entries, UInt(64.W))))
  val shapes = Seq.fill(c.sources)(Reg(Vec(c.entries, UInt(2.W))))
  val intermediates = Seq.fill(c.sources)(Reg(Vec(c.entries, UInt(math.max(1, log2Ceil(c.k*c.k)).W))))
  val hits = (0 until c.sources).map(s =>
    io.flow.bits.source === s.U && valid(s)(index) && epochs(s)(index) === epoch)
  val hit = hits.reduce(_ || _)
  val cachedShape = Mux1H(hits, shapes.map(_(index)))
  val cachedIntermediate = Mux1H(hits, intermediates.map(_(index)))
  val destRouter = io.flow.bits.destination / c.concentration.U
  val srcRouter = io.flow.bits.source / c.concentration.U
  val x = destRouter % c.k.U; val y = destRouter / c.k.U
  val rowLoad = io.columnLoads(x)
  val colLoad = io.rowLoads(y)
  val rowEnabled = (c.paths & 1) != 0
  val colEnabled = (c.paths & 2) != 0
  val valiantEnabled = (c.paths & 4) != 0
  val rowCongested = rowLoad > c.threshold.U
  val colCongested = colLoad > c.threshold.U
  val shape = WireDefault(0.U(2.W))
  if (c.forcedShape >= 0) shape := c.forcedShape.U
  else if (c.oneShapePerEpoch) {
    if (rowEnabled && colEnabled) shape := epoch(0)
    else shape := (if (colEnabled) 1 else 0).U
  } else {
    if (rowEnabled && colEnabled) {
      shape := Mux(colLoad < rowLoad, 1.U, 0.U)
      if (valiantEnabled) { when(rowCongested && colCongested) { shape := 2.U } }
    } else if (rowEnabled) {
      shape := 0.U
      if (valiantEnabled) { when(rowCongested) { shape := 2.U } }
    } else if (colEnabled) {
      shape := 1.U
      if (valiantEnabled) { when(colCongested) { shape := 2.U } }
    } else shape := 2.U
  }
  if (c.forcedShape < 0 && c.islandColumns.nonEmpty) {
    when(c.islandColumns.toSeq.map(i => x === i.U).reduce(_ || _)) { shape := 1.U }
  }
  val randomIntermediate = io.randomWord % (c.k*c.k).U
  val needsRandom = !hit && shape === 2.U
  val admissibleRandom = randomIntermediate =/= srcRouter && randomIntermediate =/= destRouter
  val result = Module(new Queue(new SrotaDecision(c), 1, pipe = false, flow = false))
  result.io.enq.valid := io.flow.valid && (!needsRandom || admissibleRandom)
  io.flow.ready := result.io.enq.ready && (!needsRandom || admissibleRandom)
  result.io.enq.bits.shape := Mux(hit, cachedShape, shape)
  result.io.enq.bits.intermediate := Mux(hit, cachedIntermediate, randomIntermediate)
  result.io.enq.bits.epoch := epoch; result.io.enq.bits.flowHash := hash
  result.io.enq.bits.cacheHit := hit
  io.decision <> result.io.deq
  // Invalid candidates are consumed for rejection sampling, without accepting
  // or changing the flow request. The caller holds flow until ready.
  io.randomUsed := io.flow.valid && result.io.enq.ready && needsRandom
  when(io.flow.fire && !hit) {
    for (s <- 0 until c.sources) {
      when(io.flow.bits.source === s.U) {
        valid(s)(index) := true.B; epochs(s)(index) := epoch
        shapes(s)(index) := shape; intermediates(s)(index) := randomIntermediate
      }
    }
  }
  when(io.flow.valid) {
    SynthAssert(io.flow.bits.source < c.sources.U)
    SynthAssert(destRouter < (c.k*c.k).U)
  }
}

/** Telemetry samples peak normalized input occupancy, rounds to a nibble,
  * averages the peaks by row/column, and publishes exactly latency cycles
  * after the periodic sample. Disabled routers contribute no load.
  */
class SrotaCreditTelemetry(k: Int, inputs: Int, period: Int, latency: Int) extends Module {
  require(k >= 2 && inputs > 0 && period > 0 && latency >= 0)
  val io = IO(new Bundle {
    val occupancy = Input(Vec(k*k, Vec(inputs, UInt(16.W))))
    val capacity = Input(Vec(k*k, Vec(inputs, UInt(16.W))))
    val enabled = Input(Vec(k*k, Bool()))
    val watermark = Input(Vec(k*k, Bool()))
    val rowLoads = Output(Vec(k, UInt(4.W)))
    val columnLoads = Output(Vec(k, UInt(4.W)))
  })
  val tick = RegInit(0.U(32.W)); tick := tick+1.U
  val sample = tick % period.U === 0.U
  val peak = (0 until k*k).map { r =>
    val ratios = (0 until inputs).map { p =>
      val cap = io.capacity(r)(p); val occ = io.occupancy(r)(p)
      val scaled = Mux(cap === 0.U, 0.U, (occ * 15.U + cap/2.U) / cap)
      Mux(scaled > 15.U, 15.U, scaled)(3, 0)
    }
    val max = ratios.reduce((a, b) => Mux(a > b, a, b))
    Mux(!io.enabled(r), 0.U, Mux(io.watermark(r), 15.U, max))
  }
  // Summing k nibbles widens the division; the published average is still a nibble.
  val rows = VecInit((0 until k).map(y => (peak.slice(y*k, (y+1)*k).reduce(_ +& _) / k.U)(3, 0)))
  val cols = VecInit((0 until k).map(x => ((0 until k).map(y => peak(y*k+x)).reduce(_ +& _) / k.U)(3, 0)))
  val due = if (latency == 0) sample else ShiftRegister(sample, latency, false.B, true.B)
  val delayedRows = if (latency == 0) rows else ShiftRegister(rows, latency)
  val delayedCols = if (latency == 0) cols else ShiftRegister(cols, latency)
  val publishedRows = RegInit(VecInit(Seq.fill(k)(0.U(4.W))))
  val publishedCols = RegInit(VecInit(Seq.fill(k)(0.U(4.W))))
  // For zero latency, a sample is visible combinationally in its sample cycle;
  // otherwise only the corresponding delayed sample can update publication.
  when(due) {
    for (i <- 0 until k) { publishedRows(i) := delayedRows(i); publishedCols(i) := delayedCols(i) }
  }
  io.rowLoads := Mux(due, delayedRows, publishedRows)
  io.columnLoads := Mux(due, delayedCols, publishedCols)
}
