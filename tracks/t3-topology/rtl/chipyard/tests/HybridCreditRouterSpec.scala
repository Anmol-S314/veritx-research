package veritx.chipyard

import chisel3._
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec

class HybridCreditRouterSpec extends AnyFlatSpec with ChiselScalatestTester {
  behavior of "hybrid credit router"

  private def cfg = CreditRouterConfig(inputs = 1, taps = Seq(1), vcs = 1,
    width = 8, depth = 2, outputDepth = 1, iterations = 1, tagBits = 8)

  private def idle(d: HybridCreditRouter): Unit = {
    d.io.in(0).valid.poke(false.B)
    d.io.in(0).bits.data.poke(0.U)
    d.io.in(0).bits.vc.poke(0.U)
    d.io.in(0).bits.head.poke(false.B)
    d.io.in(0).bits.tail.poke(false.B)
    d.io.in(0).bits.tag.poke(0.U)
    d.io.credit(0).valid.poke(false.B)
    d.io.credit(0).bits.tail.poke(false.B)
    d.io.meshLegal(0).poke(1.U)
    d.io.expressLegal(0).poke(1.U)
    d.io.meshObserve(0).poke(1.U)
    d.io.expressObserve(0).poke(1.U)
    d.io.meshHops(0).poke(1.U)
    d.io.meshTag(0).poke(0x11.U)
    d.io.expressTag(0).poke(0x22.U)
  }

  private def send(d: HybridCreditRouter, data: Int): Unit = {
    d.io.in(0).valid.poke(true.B)
    d.io.in(0).bits.data.poke(data.U)
    d.io.in(0).bits.head.poke(true.B)
    d.io.in(0).bits.tail.poke(true.B)
    d.clock.step()
    d.io.in(0).valid.poke(false.B)
  }

  private def awaitOutput(d: HybridCreditRouter): Unit = {
    var cycles = 0
    while (!d.io.out(0).valid.peek().litToBoolean && cycles < 30) {
      d.clock.step()
      cycles += 1
    }
    d.io.out(0).valid.expect(true.B)
  }

  it should "route with the express tag on an idle cost tie" in {
    test(new HybridCreditRouter(cfg)) { d =>
      idle(d)
      d.io.meshSelected(0).expect(false.B)
      send(d, 0xab)
      awaitOutput(d)
      d.io.out(0).bits.flit.data.expect(0xab.U)
      d.io.out(0).bits.flit.tag.expect(0x22.U)
    }
  }

  it should "route with the mesh tag when express offers no legal route" in {
    test(new HybridCreditRouter(cfg)) { d =>
      idle(d)
      d.io.expressLegal(0).poke(0.U)
      d.io.meshSelected(0).expect(true.B)
      send(d, 0xcd)
      awaitOutput(d)
      d.io.out(0).bits.flit.data.expect(0xcd.U)
      d.io.out(0).bits.flit.tag.expect(0x11.U)
    }
  }

  it should "hold a packet when neither route is legal" in {
    test(new HybridCreditRouter(cfg)) { d =>
      idle(d)
      d.io.meshLegal(0).poke(0.U)
      d.io.expressLegal(0).poke(0.U)
      d.io.meshSelected(0).expect(false.B)
      send(d, 0xef)
      for (_ <- 0 until 15) { d.clock.step() }
      d.io.out(0).valid.expect(false.B)
    }
  }
}
