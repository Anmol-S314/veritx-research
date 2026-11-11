package constellation.veritx

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import chisel3.stage.ChiselStage
import constellation.channel.{FlowParams, UserChannelParams, UserEgressParams, UserIngressParams, UserVirtualChannelParams}
import constellation.noc.{InternalNoCParams, LinkSpec, NoC, NoCParams, NoCTerminalIO}
import constellation.router.UserRouterParams
import constellation.routing.{ChannelRoutingInfo, FlowRoutingInfo, RoutingRelation}
import constellation.test.{NoCTesterConfig, NoCTesterParams}
import constellation.topology.{CustomTopology, PhysicalTopology, TopologyEdge}
import freechips.rocketchip.diplomacy.LazyModule
import org.chipsalliance.cde.config.Parameters

/** K-ary N-cube: non-wrapping mesh or bidirectional wrapped cube.
  * Wrapped DOR carries dimension, direction and dateline phase in the VC.
  * This is a new source implementation; qualification is NOT_RUN.
  */
final case class KNCubeProfile(k: Int = 4, dimensions: Int = 3,
    wrap: Boolean = true, payloadBits: Int = 128, bufferDepth: Int = 8) {
  require(k >= 2 && k <= 16 && dimensions >= 1 && dimensions <= 4)
  val nodes: Int = BigInt(k).pow(dimensions).toInt
  require(nodes <= 256, "KNCube source profile is limited to 256 routers")
  require(payloadBits > 0 && bufferDepth > 0)
  val vcs: Int = if (wrap) 4 * dimensions else 1
  val strides: Seq[Int] = (0 until dimensions).map(d => BigInt(k).pow(d).toInt)
  def coord(router: Int, dim: Int): Int = (router / strides(dim)) % k
  def neighbour(router: Int, dim: Int, positive: Boolean): Option[Int] = {
    val old = coord(router, dim)
    val raw = old + (if (positive) 1 else -1)
    if (!wrap && (raw < 0 || raw >= k)) None
    else Some(router + (((raw + k) % k) - old) * strides(dim))
  }
  val edges: Seq[(Int, Int)] = (for {
    src <- 0 until nodes; dim <- 0 until dimensions; positive <- Seq(true, false)
    dst <- neighbour(src, dim, positive)
  } yield (src, dst)).distinct

  /** First unresolved dimension, shortest direction; ties go positive. */
  def step(cur: Int, dst: Int): Option[(Int, Boolean, Int)] = {
    (0 until dimensions).find(d => coord(cur, d) != coord(dst, d)).map { dim =>
      val from = coord(cur, dim); val to = coord(dst, dim)
      val positive = if (!wrap) to > from
        else (to - from + k) % k <= (from - to + k) % k
      (dim, positive, neighbour(cur, dim, positive).get)
    }
  }
  def relation: PhysicalTopology => RoutingRelation = topology => new RoutingRelation(topology) {
    def rel(in: ChannelRoutingInfo, out: ChannelRoutingInfo, flow: FlowRoutingInfo): Boolean = {
      val cur = if (in.src < 0) flow.ingressNode else in.dst
      if (out.isEgress || out.src != cur) return false
      step(cur, flow.egressNode) match {
        case None => false
        case Some((dim, positive, next)) =>
          if (out.dst != next) false
          else if (!wrap) out.vc == 0
          else {
            val direction = if (positive) 0 else 1
            val crossed = if (positive) coord(cur, dim) == k - 1 else coord(cur, dim) == 0
            val transit = in.src >= 0
            val oldDim = if (transit) in.vc / 4 else -1
            val oldDirection = if (transit) (in.vc % 4) / 2 else direction
            val oldPhase = if (transit && oldDim == dim) in.vc % 2 else 0
            val phase = if (crossed) 1 else oldPhase
            oldDim <= dim && (oldDim != dim || oldDirection == direction) &&
              out.vc == 4 * dim + 2 * direction + phase
          }
      }
    }
  }
}

object CatalogRtlKNCubeExport {
  private class CandidateNoCTop(params: NoCParams)(implicit p: Parameters) extends chisel3.Module {
    private val noc = LazyModule(new NoC(params))
    val io = chisel3.IO(new NoCTerminalIO(noc.allIngressParams, noc.allEgressParams)(noc.iP))
    private val impl = chisel3.Module(noc.module)
    io.ingress.zip(impl.io.ingress).foreach { case (a, b) => a <> b }
    io.egress.zip(impl.io.egress).foreach { case (a, b) => a <> b }
    impl.io.router_clocks.foreach { c => c.clock := clock; c.reset := reset }
  }
  def main(args: Array[String]): Unit = {
    require(args.length >= 1 && args.length <= 6,
      "usage: CatalogRtlKNCubeExport <outDir> [k=4] [n=3] [wrap=true] [width=128] [buffer=8]")
    def integer(i: Int, fallback: Int): Int = if (args.length > i) args(i).toInt else fallback
    val wrap = if (args.length > 3) {
      require(Set("true", "false").contains(args(3)), "wrap must be true or false")
      args(3).toBoolean
    } else true
    val profile = KNCubeProfile(integer(1, 4), integer(2, 3), wrap, integer(4, 128), integer(5, 8))
    val out = Paths.get(args(0)).toAbsolutePath.normalize
    val topology = new CustomTopology(profile.nodes, profile.edges.map { case (s, d) => TopologyEdge(s, d) })
    val links = profile.edges.zipWithIndex.map { case ((s, d), id) => LinkSpec(id, s, d) }
    val params = NoCParams(
      topology = topology, channelLinks = Some(links),
      channelParamGen = (_, _) => UserChannelParams(virtualChannelParams =
        Seq.fill(profile.vcs)(UserVirtualChannelParams(bufferSize = profile.bufferDepth))),
      ingresses = (0 until profile.nodes).map(r => UserIngressParams(r, payloadBits = profile.payloadBits)),
      egresses = (0 until profile.nodes).map(r => UserEgressParams(r, payloadBits = profile.payloadBits)),
      flows = for (s <- 0 until profile.nodes; d <- 0 until profile.nodes) yield FlowParams(s, d, 0),
      routingRelation = profile.relation,
      routerParams = (_: Int) => UserRouterParams(payloadBits = profile.payloadBits),
      nocName = "catalog_rtl_kncube")
    val validated = InternalNoCParams(params)
    require(validated.routerParams.size == profile.nodes, "router inventory changed")
    require(validated.channelParams.map(_.linkId).toSet == links.map(_.id).toSet,
      "KNCube routing pruned a required physical link")
    implicit val p: Parameters = new NoCTesterConfig(NoCTesterParams(nocParams = params)).toInstance
    Files.createDirectories(out)
    (new ChiselStage).emitVerilog(new CandidateNoCTop(params), Array("--target-dir", out.toString))
    val inventory = s"""{"schema":"veritx/kncube-rtl/1","topology_id":"kncube","k":${profile.k},"dimensions":${profile.dimensions},"wrap":${profile.wrap},"routers":${profile.nodes},"links":${links.size},"vcs":${profile.vcs},"payload_bits":${profile.payloadBits},"buffer_depth":${profile.bufferDepth},"simulation":"NOT_RUN","qualification":"NOT_QUALIFIED","final_implementation":false}"""
    Files.write(out.resolve("rtl_inventory.json"), inventory.getBytes(StandardCharsets.UTF_8))
  }
}
