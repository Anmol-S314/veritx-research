package veritx.chipyard

import chisel3._
import chisel3.util._

/** CreditRouter with one HybridRoutePolicy per input VC. The policy reads the
  * router's actual slot free counts, so mesh cost is used-credit x hops over
  * real occupancy and ties select express. Route alternatives and tags come
  * from the native source; the router keeps ownership for the whole packet.
  */
class HybridCreditRouter(c: CreditRouterConfig, distanceBits: Int = 8) extends Module {
  require(distanceBits > 0)
  val io = IO(new Bundle {
    val in = Flipped(Vec(c.inputs, Valid(new CreditPacketFlit(c))))
    val returned = Output(Vec(c.inputs, Vec(c.vcs, Valid(new CreditPulse))))
    val out = Vec(c.outputs, Valid(new CreditRouterOutput(c)))
    val credit = Flipped(Vec(c.slots, Valid(new CreditPulse)))
    val meshLegal = Input(Vec(c.lanes, UInt(c.slots.W)))
    val expressLegal = Input(Vec(c.lanes, UInt(c.slots.W)))
    val meshObserve = Input(Vec(c.lanes, UInt(c.slots.W)))
    val expressObserve = Input(Vec(c.lanes, UInt(c.slots.W)))
    val meshHops = Input(Vec(c.lanes, UInt(distanceBits.W)))
    val meshTag = Input(Vec(c.lanes, UInt(c.tagBits.W)))
    val expressTag = Input(Vec(c.lanes, UInt(c.tagBits.W)))
    val meshSelected = Output(Vec(c.lanes, Bool()))
    val free = Output(Vec(c.slots, UInt(log2Ceil(c.depth + 1).W)))
    val occupied = Output(Vec(c.slots, Bool()))
    val inputOccupancy = Output(Vec(c.inputs, Vec(c.vcs, UInt(log2Ceil(c.depth + 1).W))))
  })
  val router = Module(new CreditRouter(c))
  router.io.in := io.in
  io.returned := router.io.returned
  io.out := router.io.out
  router.io.credit := io.credit
  io.free := router.io.free
  io.occupied := router.io.occupied
  io.inputOccupancy := router.io.inputOccupancy

  for (l <- 0 until c.lanes) {
    val policy = Module(new HybridRoutePolicy(c.slots, c.depth, distanceBits, c.tagBits))
    policy.suggestName(s"route_policy_${l}")
    policy.io.meshLegal := io.meshLegal(l)
    policy.io.expressLegal := io.expressLegal(l)
    policy.io.meshObserve := io.meshObserve(l)
    policy.io.expressObserve := io.expressObserve(l)
    policy.io.free := router.io.free
    policy.io.meshHops := io.meshHops(l)
    policy.io.meshTag := io.meshTag(l)
    policy.io.expressTag := io.expressTag(l)
    // The policy chooses between two one-hot route masks; the router takes a
    // slot index, so the chosen mask is decoded once per lane.
    router.io.route(l).slot := PriorityEncoder(policy.io.legal)
    router.io.route(l).valid := policy.io.legal.orR
    router.io.route(l).tag := policy.io.tag
    io.meshSelected(l) := policy.io.meshSelected
  }
}
