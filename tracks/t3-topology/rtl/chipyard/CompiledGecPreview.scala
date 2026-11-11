package veritx.chipyard

import chisel3._
import chisel3.util._
import chisel3.stage.ChiselStage

/** Shared-resource topology preview. See contract.json for unrealized router semantics. */
class GecTransfer extends Bundle {
  val flit = UInt(SelectedGec.width.W)
  val next = UInt(log2Ceil(SelectedGec.routers).W)
}

class CompiledGecPreview extends Module {
  import SelectedGec._
  val io = IO(new Bundle {
    val ingress = Vec(endpoints.size, Flipped(Decoupled(UInt(width.W))))
    val egress = Vec(endpoints.size, Decoupled(UInt(width.W)))
    val wireFire = Output(Vec(wires.size, Bool()))
  })
  def dest(f: UInt): UInt = f(destLsb + destWidth - 1, destLsb)
  def vc(f: UInt): UInt = f(vcLsb + vcWidth - 1, vcLsb)
  val vcMask = ((BigInt(1) << width) - 1) ^ (((BigInt(1) << vcWidth) - 1) << vcLsb)
  def withVc(f: UInt, v: UInt): UInt = (f & vcMask.U(width.W)) | (v << vcLsb)
  val endpointRouter = VecInit(endpoints.map(_.U(log2Ceil(routers).W)))
  val buses = wires.indices.map { w =>
    val q = Module(new Queue(new GecTransfer, 1, pipe = false, flow = false))
    q.suggestName(s"shared_wire_${w}")
    q.io.enq.valid := false.B; q.io.enq.bits := 0.U.asTypeOf(new GecTransfer)
    q.io.deq.ready := false.B
    io.wireFire(w) := q.io.deq.fire
    q
  }
  for (e <- endpoints.indices) {
    io.ingress(e).ready := false.B
    io.egress(e).valid := false.B; io.egress(e).bits := 0.U
    when(io.ingress(e).valid) {
      assert(dest(io.ingress(e).bits) < endpoints.size.U, "invalid endpoint")
      assert(vc(io.ingress(e).bits) < vcs.U, "invalid VC")
      assert(io.ingress(e).bits(typeLsb + 1, typeLsb) === 3.U, "preview accepts SINGLE flits only")
    }
  }
  for (r <- 0 until routers) {
    val local = endpoints.indices.filter(endpoints(_) == r)
    val incoming = wires.indices.filter(w => wires(w)._2.contains(r))
    val inputs = Module(new RRArbiter(UInt(width.W), local.size + incoming.size))
    for ((e, i) <- local.zipWithIndex) { inputs.io.in(i) <> io.ingress(e) }
    for ((w, i) <- incoming.zipWithIndex) {
      val input = inputs.io.in(local.size + i)
      input.valid := buses(w).io.deq.valid && buses(w).io.deq.bits.next === r.U
      input.bits := buses(w).io.deq.bits.flit
      when(buses(w).io.deq.bits.next === r.U) { buses(w).io.deq.ready := input.ready }
    }
    val queues = (0 until vcs).map { v =>
      val q = Module(new Queue(UInt(width.W), depth, pipe = false, flow = false))
      q.suggestName(s"router_${r}_vc_${v}")
      q.io.enq.valid := inputs.io.out.valid && vc(inputs.io.out.bits) === v.U
      q.io.enq.bits := inputs.io.out.bits
      q
    }
    inputs.io.out.ready := VecInit(queues.map(_.io.enq.ready))(vc(inputs.io.out.bits))
    val outputs = Module(new RRArbiter(UInt(width.W), vcs))
    for (v <- 0 until vcs) { outputs.io.in(v) <> queues(v).io.deq }
    // Register the arbitration result so a newly arriving contender cannot
    // change the presented payload while a shared wire or endpoint is stalled.
    val held = Queue(outputs.io.out, 1, pipe = false, flow = false)
    held.ready := false.B
    val endpoint = dest(held.bits)
    val destination = endpointRouter(endpoint)
    val routeWire = VecInit(routes(r).map(x => (x._1 + 1).U(log2Ceil(wires.size + 1).W)))(destination)
    val routeNext = VecInit(routes(r).map(_._2.U(log2Ceil(routers).W)))(destination)
    val routeVc = VecInit(routes(r).map(_._3.U(vcWidth.W)))(destination)
    for (e <- local) {
      io.egress(e).valid := held.valid && endpoint === e.U
      io.egress(e).bits := held.bits
      when(endpoint === e.U) { held.ready := io.egress(e).ready }
    }
    for (w <- wires.indices.filter(wires(_)._1 == r)) {
      buses(w).io.enq.valid := held.valid && routeWire === (w + 1).U
      buses(w).io.enq.bits.flit := withVc(held.bits, routeVc)
      buses(w).io.enq.bits.next := routeNext
      when(routeWire === (w + 1).U) { held.ready := buses(w).io.enq.ready }
    }
  }
}

object EmitCompiledGecPreview extends App {
  require(args.length == 1, "output directory required")
  (new ChiselStage).emitVerilog(new CompiledGecPreview, Array("--target-dir", args(0)))
  println(s"EMITTED contract=${SelectedGec.contractHash} routers=${SelectedGec.routers} vcs=${SelectedGec.vcs} shared_wires=${SelectedGec.wires.size}")
}
