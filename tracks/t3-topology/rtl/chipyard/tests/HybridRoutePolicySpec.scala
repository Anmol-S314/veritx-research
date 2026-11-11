package veritx.chipyard

import chisel3._
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec

class HybridRoutePolicySpec extends AnyFlatSpec with ChiselScalatestTester {
  behavior of "hybrid GEC route policy"

  private def idle(d: HybridRoutePolicy): Unit = {
    d.io.meshLegal.poke(0.U)
    d.io.expressLegal.poke(0.U)
    d.io.meshObserve.poke(0.U)
    d.io.expressObserve.poke(0.U)
    d.io.meshHops.poke(0.U)
    d.io.meshTag.poke(0x11L.U(32.W))
    d.io.expressTag.poke(0x22L.U(32.W))
    for (s <- 0 until 2) { d.io.free(s).poke(8.U) }
  }

  it should "select express on an exact cost tie" in {
    test(new HybridRoutePolicy(slots = 2, depth = 8, distanceBits = 4)) { d =>
      idle(d)
      d.io.meshLegal.poke(1.U)
      d.io.expressLegal.poke(2.U)
      d.io.meshObserve.poke(1.U)
      d.io.expressObserve.poke(2.U)
      d.io.meshHops.poke(5.U)
      d.io.free(0).poke(8.U)
      d.io.free(1).poke(8.U)
      d.io.legal.expect(2.U)
      d.io.tag.expect(0x22L.U(32.W))
      d.io.meshSelected.expect(false.B)
    }
  }

  it should "prefer mesh only when observed used-credit times hops is lower" in {
    test(new HybridRoutePolicy(slots = 2, depth = 8, distanceBits = 4)) { d =>
      idle(d)
      d.io.meshLegal.poke(1.U)
      d.io.expressLegal.poke(2.U)
      d.io.meshObserve.poke(1.U)
      d.io.expressObserve.poke(2.U)
      d.io.free(0).poke(6.U) // mesh: 2 used
      d.io.free(1).poke(2.U) // express: 6 used
      d.io.meshHops.poke(2.U) // mesh cost 4 < 6
      d.io.legal.expect(1.U)
      d.io.tag.expect(0x11L.U(32.W))
      d.io.meshSelected.expect(true.B)

      // Observing the heavily used express slot raises mesh cost to 16.
      d.io.meshObserve.poke(3.U)
      d.io.legal.expect(2.U)
      d.io.tag.expect(0x22L.U(32.W))
      d.io.meshSelected.expect(false.B)
    }
  }

  it should "let a mesh-only request ignore a congested express mask" in {
    test(new HybridRoutePolicy(slots = 2, depth = 8, distanceBits = 4)) { d =>
      idle(d)
      d.io.meshLegal.poke(1.U)
      d.io.expressObserve.poke(2.U)
      d.io.free(1).poke(0.U) // express fully used
      d.io.meshHops.poke(1.U)
      d.io.legal.expect(1.U)
      d.io.tag.expect(0x11L.U(32.W))
      d.io.meshSelected.expect(true.B)
    }
  }

  it should "keep the legal mask empty when no route is legal" in {
    test(new HybridRoutePolicy(slots = 2, depth = 8, distanceBits = 4)) { d =>
      idle(d)
      d.io.meshHops.poke(0.U)
      d.io.legal.expect(0.U)
      d.io.meshSelected.expect(false.B)

      d.io.expressLegal.poke(2.U)
      d.io.legal.expect(2.U)
      d.io.tag.expect(0x22L.U(32.W))
    }
  }

  it should "not count a full slot that its mask does not observe" in {
    test(new HybridRoutePolicy(slots = 2, depth = 8, distanceBits = 4)) { d =>
      idle(d)
      d.io.meshLegal.poke(1.U)
      d.io.expressLegal.poke(2.U)
      d.io.meshHops.poke(7.U)
      d.io.free(0).poke(0.U)
      d.io.free(1).poke(0.U)
      // Both observed used counts are zero, so the tie goes to express.
      d.io.legal.expect(2.U)
      d.io.meshSelected.expect(false.B)
    }
  }
}
