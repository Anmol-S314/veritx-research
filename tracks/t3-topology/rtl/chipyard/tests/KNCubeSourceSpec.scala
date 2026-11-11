package constellation.veritx

import org.scalatest.flatspec.AnyFlatSpec
import constellation.routing.{ChannelRoutingInfo, FlowRoutingInfo}
import constellation.topology.{CustomTopology, TopologyEdge}

/** Pure profile/relation tests. They do not elaborate a hardware module. */
class KNCubeSourceSpec extends AnyFlatSpec {
  behavior of "KNCube profile and dateline routing"

  it should "build actual n-dimensional wiring rather than an aliased mesh" in {
    val cube = KNCubeProfile()
    assert(cube.nodes == 64)
    assert(cube.edges.size == 384)
    assert(cube.vcs == 12)
    assert(cube.edges.contains((0, 3)))
    assert(cube.edges.contains((0, 12)))
    assert(cube.edges.contains((0, 48)))
    val mesh = KNCubeProfile(k = 4, dimensions = 2, wrap = false)
    assert(mesh.edges.size == 48)
    assert(mesh.vcs == 1)
    assert(!mesh.edges.contains((0, 3)))
  }

  it should "deduplicate coincident directions at radix two" in {
    val cube = KNCubeProfile(k = 2, dimensions = 2)
    assert(cube.edges.size == 8)
    assert(cube.edges.distinct == cube.edges)
  }

  it should "carry direction and dateline phase and reset phase on a later dimension" in {
    val cube = KNCubeProfile(k = 4, dimensions = 2)
    val topology = new CustomTopology(cube.nodes, cube.edges.map { case (s, d) => TopologyEdge(s, d) })
    val route = cube.relation(topology)
    def flow(src: Int, dst: Int) = FlowRoutingInfo(
      ingressId = src, egressId = dst, vNetId = 0,
      ingressNode = src, ingressNodeId = 0,
      egressNode = dst, egressNodeId = 0, fifo = false)
    val injection = ChannelRoutingInfo(src = -1, dst = 0, vc = 0, n_vc = 1)
    val negativeWrap = ChannelRoutingInfo(src = 0, dst = 3, vc = 3, n_vc = cube.vcs)
    assert(route(injection, negativeWrap, flow(0, 3)))
    assert(!route(injection, negativeWrap.copy(vc = 2), flow(0, 3)))
    // After the X wrap, Y starts with phase zero rather than inheriting X's phase.
    val nextDimension = ChannelRoutingInfo(src = 3, dst = 7, vc = 4, n_vc = cube.vcs)
    assert(route(negativeWrap, nextDimension, flow(0, 7)))
    assert(!route(negativeWrap, nextDimension.copy(vc = 5), flow(0, 7)))
    val positiveWrap = ChannelRoutingInfo(src = 3, dst = 0, vc = 1, n_vc = cube.vcs)
    assert(route(ChannelRoutingInfo(src = -1, dst = 3, vc = 0, n_vc = 1), positiveWrap, flow(3, 0)))
  }

  it should "reject oversized or invalid geometries" in {
    intercept[IllegalArgumentException](KNCubeProfile(k = 1))
    intercept[IllegalArgumentException](KNCubeProfile(k = 16, dimensions = 4))
    intercept[IllegalArgumentException](KNCubeProfile(bufferDepth = 0))
  }
}
