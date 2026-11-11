package veritx.chipyard

import chisel3._
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec
import scala.collection.mutable.ArrayBuffer

class CreditRouterSpec extends AnyFlatSpec with ChiselScalatestTester {
  behavior of "credit ownership and packet routing"

  it should "separate slot credits from tail-credit VC ownership" in {
    test(new CreditOwnership(2, 2, true)) { d =>
      for (s <- 0 until 2) {
        d.io.reserve(s).poke(false.B); d.io.send(s).poke(false.B); d.io.sendTail(s).poke(false.B)
        d.io.returned(s).valid.poke(false.B); d.io.returned(s).bits.tail.poke(false.B)
      }
      d.io.reserve(0).poke(true.B); d.clock.step(); d.io.reserve(0).poke(false.B)
      d.io.send(0).poke(true.B); d.clock.step()
      d.io.sendTail(0).poke(true.B); d.clock.step()
      d.io.send(0).poke(false.B); d.io.sendTail(0).poke(false.B)
      d.io.free(0).expect(0.U); d.io.occupied(0).expect(true.B)
      d.io.waitingTail(0).expect(true.B)
      d.io.returned(0).valid.poke(true.B); d.clock.step()
      d.io.free(0).expect(1.U); d.io.occupied(0).expect(true.B)
      d.io.returned(0).bits.tail.poke(true.B); d.clock.step()
      d.io.free(0).expect(2.U); d.io.occupied(0).expect(false.B)
      d.io.returned(0).valid.poke(false.B)
      d.io.free(1).expect(2.U)
    }
  }

  it should "match contending rows without duplicate grants and rotate committed winners" in {
    test(new CreditMatch(2, 2, 2, true)) { d =>
      d.io.request(0).poke(3.U); d.io.request(1).poke(3.U)
      d.io.commit(0).poke(0.U); d.io.commit(1).poke(0.U)
      val seen = ArrayBuffer.empty[(BigInt, BigInt)]
      for (_ <- 0 until 6) {
        val a = d.io.matched(0).peek().litValue
        val b = d.io.matched(1).peek().litValue
        assert(a != 0 && b != 0 && (a & b) == 0)
        assert(a.bitCount == 1 && b.bitCount == 1)
        seen += ((a, b))
        d.io.commit(0).poke(a.U); d.io.commit(1).poke(b.U); d.clock.step()
      }
      assert(seen.distinct.size == 2)
    }
  }

  it should "forward HEAD BODY TAIL, exhaust credits, and retain ownership until the tail credit" in {
    val c = CreditRouterConfig(inputs = 1, taps = Seq(1), vcs = 1,
      width = 32, depth = 2, outputDepth = 1, iterations = 1)
    test(new CreditRouter(c)) { d =>
      d.io.in(0).valid.poke(false.B)
      d.io.credit(0).valid.poke(false.B); d.io.credit(0).bits.tail.poke(false.B)
      d.io.route(0).slot.poke(0.U); d.io.route(0).valid.poke(true.B)
      d.io.route(0).tag.poke(0x55.U)
      val input = Seq((11, true, false), (22, false, false), (33, false, true), (44, true, true))
      val output = ArrayBuffer.empty[(Int, Boolean, Boolean)]
      var injected = 0
      var ingressCredits = 2
      def tick(returnCredit: Boolean = false, tailCredit: Boolean = false): Unit = {
        val send = injected < input.size && ingressCredits > 0
        d.io.in(0).valid.poke(send.B)
        val f = if (send) input(injected) else (0, false, false)
        d.io.in(0).bits.data.poke(f._1.U)
        d.io.in(0).bits.vc.poke(0.U)
        d.io.in(0).bits.head.poke(f._2.B); d.io.in(0).bits.tail.poke(f._3.B)
        d.io.in(0).bits.tag.poke(0.U)
        d.io.credit(0).valid.poke(returnCredit.B); d.io.credit(0).bits.tail.poke(tailCredit.B)
        val returned = d.io.returned(0)(0).valid.peek().litToBoolean
        if (d.io.out(0).valid.peek().litToBoolean) {
          val out = d.io.out(0).bits.flit
          output += ((out.data.peek().litValue.toInt, out.head.peek().litToBoolean, out.tail.peek().litToBoolean))
          out.tag.expect(0x55.U); out.vc.expect(0.U); d.io.out(0).bits.tap.expect(0.U)
        }
        d.clock.step()
        if (send) { injected += 1; ingressCredits -= 1 }
        if (returned) ingressCredits += 1
        assert(ingressCredits >= 0 && ingressCredits <= 2)
      }
      for (_ <- 0 until 40) tick()
      assert(output.toSeq == input.take(2))
      d.io.free(0).expect(0.U); d.io.occupied(0).expect(true.B)
      tick(returnCredit = true)
      tick(returnCredit = true)
      for (_ <- 0 until 30) tick()
      assert(output.toSeq == input.take(3))
      d.io.occupied(0).expect(true.B)
      // The second packet must not acquire the still-owned VC despite a free slot.
      d.io.free(0).expect(1.U)
      tick(returnCredit = true, tailCredit = true)
      for (_ <- 0 until 30) tick()
      assert(output.toSeq == input)
      assert(injected == 4)
      tick(returnCredit = true, tailCredit = true)
      d.io.occupied(0).expect(false.B); d.io.free(0).expect(2.U)
    }
  }

  it should "route simultaneous lanes to distinct outputs through selected slots" in {
    val c = CreditRouterConfig(inputs = 2, taps = Seq(1, 1), vcs = 2,
      width = 32, depth = 2, outputDepth = 1, iterations = 1)
    test(new CreditRouter(c)) { d =>
      for (p <- 0 until c.inputs) {
        d.io.in(p).valid.poke(false.B)
        d.io.in(p).bits.data.poke(0.U); d.io.in(p).bits.vc.poke(0.U)
        d.io.in(p).bits.head.poke(false.B); d.io.in(p).bits.tail.poke(false.B)
        d.io.in(p).bits.tag.poke(0.U)
      }
      for (s <- 0 until c.slots) {
        d.io.credit(s).valid.poke(false.B); d.io.credit(s).bits.tail.poke(false.B)
      }
      for (l <- 0 until c.lanes) {
        d.io.route(l).slot.poke(0.U); d.io.route(l).valid.poke(false.B)
        d.io.route(l).tag.poke(0.U)
      }
      d.io.route(0).slot.poke(0.U); d.io.route(0).valid.poke(true.B) // input 0, VC 0 -> output 0, VC 0
      d.io.route(1).slot.poke(0.U); d.io.route(1).valid.poke(false.B)
      d.io.route(2).slot.poke(2.U); d.io.route(2).valid.poke(true.B) // input 1, VC 0 -> output 1, VC 0
      d.io.route(3).slot.poke(0.U); d.io.route(3).valid.poke(false.B)

      for ((p, data) <- Seq(0 -> 11, 1 -> 22)) {
        d.io.in(p).valid.poke(true.B); d.io.in(p).bits.data.poke(data.U)
        d.io.in(p).bits.vc.poke(0.U)
        d.io.in(p).bits.head.poke(true.B); d.io.in(p).bits.tail.poke(true.B)
      }
      d.clock.step()
      for (p <- 0 until c.inputs) d.io.in(p).valid.poke(false.B)

      val observed = scala.collection.mutable.Map.empty[Int, Int]
      for (_ <- 0 until 20) {
        for (o <- 0 until c.outputs if d.io.out(o).valid.peek().litToBoolean) {
          observed(o) = d.io.out(o).bits.flit.data.peek().litValue.toInt
          d.io.out(o).bits.flit.vc.expect(0.U)
        }
        d.clock.step()
      }
      assert(observed.toMap == Map(0 -> 11, 1 -> 22))
    }
  }
}
