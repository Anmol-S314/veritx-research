package veritx.chipyard

import java.io.{ByteArrayInputStream, DataInputStream}
import java.security.MessageDigest
import chisel3._
import chisel3.util._
import chisel3.stage.ChiselStage

final case class FabricResource(src: Int, taps: Seq[Int], latency: Int)
final case class FabricHop(resource: Int, next: Int, vcs: BigInt)
final case class FabricContract(routers: Int, width: Int, vcs: Int, depth: Int,
    destLsb: Int, destWidth: Int, vcLsb: Int, vcWidth: Int,
    typeLsb: Int, typeWidth: Int, ingress: Seq[Int], egress: Seq[Int],
    resources: Seq[FabricResource], paths: Seq[Seq[FabricHop]], choices: Seq[Seq[Int]]) {
  require(routers > 0 && width > 0 && vcs > 0 && depth > 0)
  require(ingress.nonEmpty && ingress.size == egress.size)
  require(choices.size == ingress.size * ingress.size && choices.forall(_.nonEmpty))
  require(paths.nonEmpty)
  require(resources.forall(r => r.latency >= 1 && r.taps.nonEmpty))
}
object FabricContract {
  def load(resource: String, expectedSha: String): FabricContract = {
    val source = Option(getClass.getResourceAsStream(resource)).getOrElse(
      throw new IllegalArgumentException(s"missing compiled fabric data: $resource"))
    val bytes = try source.readAllBytes() finally source.close()
    val actual = MessageDigest.getInstance("SHA-256").digest(bytes).map(b => f"${b & 0xff}%02x").mkString
    require(actual == expectedSha, "compiled fabric binary identity mismatch")
    val data = new DataInputStream(new ByteArrayInputStream(bytes))
    def int(): Int = data.readInt()
    def count(max: Int): Int = { val n = int(); require(n >= 0 && n <= max); n }
    def vector(max: Int): Seq[Int] = Vector.fill(count(max))(int())
    require(int() == 0x56545831, "invalid compiled fabric binary version")
    val routers = int(); val width = int(); val vcs = int(); val depth = int()
    val destLsb = int(); val destWidth = int(); val vcLsb = int(); val vcWidth = int()
    val typeLsb = int(); val typeWidth = int()
    val ingress = vector(256); val egress = vector(256)
    val resources = Vector.fill(count(65536)) {
      val src = int(); val latency = int(); FabricResource(src, vector(1024), latency)
    }
    val paths = Vector.fill(count(131072)) {
      Vector.fill(count(1024)) {
        val resource = int(); val next = int(); val allowed = vector(64)
        require(allowed.nonEmpty && allowed.forall(v => v >= 0 && v < vcs))
        FabricHop(resource, next, allowed.foldLeft(BigInt(0))((mask, v) => mask.setBit(v)))
      }
    }
    val choices = Vector.fill(count(65536))(vector(1024))
    require(data.available() == 0, "trailing compiled fabric data")
    data.close()
    FabricContract(routers, width, vcs, depth, destLsb, destWidth, vcLsb, vcWidth,
      typeLsb, typeWidth, ingress, egress, resources, paths, choices)
  }
}

class FabricInjection(c: FabricContract) extends Bundle {
  val flit = UInt(c.width.W)
  // Explicit choice among the compiler-recorded alternatives for this pair.
  // This is not a substitute for the family's native congestion/FIU selector.
  val routeChoice = UInt(math.max(1, log2Ceil(c.choices.map(_.size).max)).W)
}
class FabricTransfer(c: FabricContract) extends Bundle {
  val flit = UInt(c.width.W)
  val path = UInt(math.max(1, log2Ceil(c.paths.size)).W)
  val hop = UInt(math.max(1, log2Ceil(c.paths.map(_.size).max + 2)).W)
  val next = UInt(math.max(1, log2Ceil(c.routers)).W)
}

/** Topology-independent physical fabric: point-to-point and true shared resources.
  * Routes, endpoint maps, VCs and widths are supplied by one frozen contract.
  * SINGLE-flit preview only; compiled credit/iSLIP semantics are not claimed.
  */
class CompiledFabricPreview(c: FabricContract = SelectedFabric.params) extends Module {
  val n = c.ingress.size
  val maxHops = c.paths.map(_.size).max
  val io = IO(new Bundle {
    val ingress = Vec(n, Flipped(Decoupled(new FabricInjection(c))))
    val egress = Vec(n, Decoupled(UInt(c.width.W)))
    val resourceFire = Output(Vec(c.resources.size, Bool()))
  })
  def dest(f: UInt): UInt = f(c.destLsb + c.destWidth - 1, c.destLsb)
  def vc(f: UInt): UInt = f(c.vcLsb + c.vcWidth - 1, c.vcLsb)
  val vcMask = ((BigInt(1) << c.width) - 1) ^ (((BigInt(1) << c.vcWidth) - 1) << c.vcLsb)
  def withVc(f: UInt, v: UInt): UInt = (f & vcMask.U(c.width.W)) | (v << c.vcLsb)
  val pathLengths = VecInit(c.paths.map(_.size.U))
  val resourceBits = math.max(1, log2Ceil(c.resources.size + 1))
  val routerBits = math.max(1, log2Ceil(c.routers))
  val routeResources = VecInit(c.paths.map { path =>
    VecInit((path.map(h => (h.resource + 1).U(resourceBits.W)) ++
      Seq.fill(maxHops + 1 - path.size)(0.U(resourceBits.W))))
  })
  val routeNext = VecInit(c.paths.map { path =>
    VecInit(path.map(_.next.U(routerBits.W)) ++ Seq.fill(maxHops + 1 - path.size)(0.U(routerBits.W)))
  })
  val routeVcs = VecInit(c.paths.map { path =>
    VecInit(path.map(_.vcs.U(c.vcs.W)) ++ Seq.fill(maxHops + 1 - path.size)(0.U(c.vcs.W)))
  })
  val injected = Wire(Vec(n, Decoupled(new FabricTransfer(c))))
  for (e <- 0 until n) {
    val choices = c.choices.slice(e*n, (e+1)*n)
    val maxChoices = choices.map(_.size).max
    val choiceCounts = VecInit(choices.map(_.size.U))
    val table = VecInit(choices.map(row => VecInit(
      (row ++ Seq.fill(maxChoices - row.size)(row.head)).map(_.U))))
    val input = io.ingress(e)
    val validEndpoint = dest(input.bits.flit) < n.U
    val validChoice = validEndpoint && input.bits.routeChoice < choiceCounts(dest(input.bits.flit))
    injected(e).valid := input.valid && validChoice
    input.ready := injected(e).ready && validChoice
    injected(e).bits.flit := input.bits.flit
    injected(e).bits.path := table(dest(input.bits.flit))(input.bits.routeChoice)
    injected(e).bits.hop := 0.U
    injected(e).bits.next := c.ingress(e).U
    when(input.valid) {
      assert(validChoice, "endpoint/route choice is outside the compiled contract")
      assert(vc(input.bits.flit) < c.vcs.U, "invalid input VC")
      assert(input.bits.flit(c.typeLsb + c.typeWidth - 1, c.typeLsb) === 3.U,
        "compiled fabric preview accepts SINGLE flits only")
    }
    io.egress(e).valid := false.B; io.egress(e).bits := 0.U
  }
  val buses = c.resources.zipWithIndex.map { case (resource, id) =>
    val input = Wire(Decoupled(new FabricTransfer(c)))
    input.valid := false.B; input.bits := 0.U.asTypeOf(new FabricTransfer(c))
    var output = input
    // One pipeline per physical resource, not one independent link per tap.
    for (cycle <- 0 until resource.latency) {
      output = Queue(output, 1, pipe = false, flow = false)
    }
    output.ready := false.B
    io.resourceFire(id) := output.fire
    (input, output)
  }
  for (r <- 0 until c.routers) {
    val local = c.ingress.indices.filter(c.ingress(_) == r)
    val incoming = c.resources.indices.filter(i => c.resources(i).taps.contains(r))
    if (local.nonEmpty || incoming.nonEmpty) {
      val arb = Module(new RRArbiter(new FabricTransfer(c), local.size + incoming.size))
      for ((e, i) <- local.zipWithIndex) { arb.io.in(i) <> injected(e) }
      for ((resource, i) <- incoming.zipWithIndex) {
        val input = arb.io.in(local.size + i)
        val bus = buses(resource)._2
        input.valid := bus.valid && bus.bits.next === r.U
        input.bits := bus.bits
        when(bus.bits.next === r.U) { bus.ready := input.ready }
      }
      val queues = (0 until c.vcs).map { v =>
        val q = Module(new Queue(new FabricTransfer(c), c.depth, pipe = false, flow = false))
        q.suggestName(s"router_${r}_vc_${v}")
        q.io.enq.valid := arb.io.out.valid && vc(arb.io.out.bits.flit) === v.U
        q.io.enq.bits := arb.io.out.bits
        q
      }
      arb.io.out.ready := VecInit(queues.map(_.io.enq.ready))(vc(arb.io.out.bits.flit))
      val out = Module(new RRArbiter(new FabricTransfer(c), c.vcs))
      for (v <- 0 until c.vcs) { out.io.in(v) <> queues(v).io.deq }
      val held = Queue(out.io.out, 1, pipe = false, flow = false)
      held.ready := false.B
      val finished = held.bits.hop === pathLengths(held.bits.path)
      val resource = routeResources(held.bits.path)(held.bits.hop)
      val next = routeNext(held.bits.path)(held.bits.hop)
      val allowed = routeVcs(held.bits.path)(held.bits.hop)
      val previousVc = vc(held.bits.flit)
      // Retain an allowed VC; otherwise choose the lowest recorded legal VC.
      val nextVc = Mux(allowed(previousVc), previousVc, PriorityEncoder(allowed))
      for (e <- c.egress.indices.filter(c.egress(_) == r)) {
        io.egress(e).valid := held.valid && finished && dest(held.bits.flit) === e.U
        io.egress(e).bits := held.bits.flit
        when(finished && dest(held.bits.flit) === e.U) { held.ready := io.egress(e).ready }
      }
      for (id <- c.resources.indices.filter(c.resources(_).src == r)) {
        val bus = buses(id)._1
        bus.valid := held.valid && !finished && resource === (id + 1).U
        bus.bits := held.bits
        bus.bits.flit := withVc(held.bits.flit, nextVc)
        bus.bits.hop := held.bits.hop + 1.U
        bus.bits.next := next
        when(!finished && resource === (id + 1).U) { held.ready := bus.ready }
      }
      when(held.valid) {
        assert(held.bits.hop <= pathLengths(held.bits.path), "path pointer overflow")
        when(!finished) { assert(allowed.orR, "recorded route has no legal VC") }
      }
    }
  }
}
object EmitCompiledFabricPreview extends App {
  require(args.length == 1, "usage: EmitCompiledFabricPreview <new output directory>")
  require(!java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))), "output directory must be new")
  (new ChiselStage).emitVerilog(new CompiledFabricPreview, Array("--target-dir", args(0)))
}
