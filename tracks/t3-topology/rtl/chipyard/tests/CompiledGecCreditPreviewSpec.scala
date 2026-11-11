package veritx.chipyard

import chisel3._
import chiseltest._
import chiseltest.simulator.VerilatorBackendAnnotation
import org.scalatest.flatspec.AnyFlatSpec
import scala.collection.mutable

class CompiledGecCreditPreviewSpec extends AnyFlatSpec with ChiselScalatestTester {
  behavior of "compiled GEC credit preview"

  private val n = SelectedGec.endpoints.size
  private val width = SelectedGec.width
  private val dataMask = (BigInt(1) << width) - 1
  private val vcMask = ((BigInt(1) << SelectedGec.vcWidth) - 1) << SelectedGec.vcLsb
  private val preserveMask = dataMask ^ vcMask

  private def flit(src: Int, dst: Int, kind: Int, sequence: Int, inputVc: Int): BigInt = {
    val payloadMask = (BigInt(1) << SelectedGec.sourceLsb) - 1
    val payload = ((BigInt(1) << (SelectedGec.sourceLsb - 1)) |
      (BigInt(src + 1) << (SelectedGec.sourceLsb / 2)) |
      (BigInt(dst + 1) << (SelectedGec.sourceLsb / 3)) |
      BigInt(sequence * 0x1f123bb5L & 0xffffffffL)) & payloadMask
    payload | (BigInt(src) << SelectedGec.sourceLsb) |
      (BigInt(dst) << SelectedGec.destLsb) |
      (BigInt(kind) << SelectedGec.typeLsb) | (BigInt(inputVc) << SelectedGec.vcLsb)
  }

  it should "route every pair, preserve packets through stalls, and drain contention" in {
    test(new CompiledGecCreditPreview(exposeDiagnostics = true)).withAnnotations(Seq(VerilatorBackendAnnotation)) { d =>
      val diagnostics = d.io.asInstanceOf[CompiledGecCreditPreviewWithDiagnosticsIO]
      for (e <- 0 until n) {
        d.io.ingress(e).valid.poke(false.B)
        d.io.ingress(e).bits.poke(0.U)
        d.io.egress(e).ready.poke(true.B)
      }

      def stepAndCheck(expectedEndpoint: Int, expectedFlit: BigInt): Boolean = {
        var observed = false
        for (e <- 0 until n if d.io.egress(e).valid.peek().litToBoolean) {
          assert(e == expectedEndpoint, s"flit delivered to endpoint $e, expected $expectedEndpoint")
          val actual = d.io.egress(e).bits.peek().litValue
          assert(actual == expectedFlit, f"payload/header mismatch: got 0x$actual%x expected 0x$expectedFlit%x")
          assert(!observed, "one input flit was delivered more than once in a cycle")
          observed = true
        }
        observed
      }

      def inject(src: Int, raw: BigInt): Unit = {
        d.io.ingress(src).bits.poke(raw.U(width.W))
        d.io.ingress(src).valid.poke(true.B)
        var accepted = false
        var cycles = 0
        while (!accepted && cycles < 1000) {
          val fire = d.io.ingress(src).ready.peek().litToBoolean
          d.clock.step()
          if (fire) {
            accepted = true
            d.io.ingress(src).valid.poke(false.B)
          }
          cycles += 1
        }
        assert(accepted, s"endpoint $src did not receive an ingress credit")
      }

      def transact(src: Int, dst: Int, sequence: Int): Unit = {
        val raw = flit(src, dst, kind = 3, sequence = sequence, inputVc = 1)
        val expected = raw & preserveMask
        d.io.ingress(src).bits.poke(raw.U(width.W))
        d.io.ingress(src).valid.poke(true.B)
        var accepted = false
        var delivered = false
        var cycles = 0
        while ((!accepted || !delivered) && cycles < 1000) {
          val fire = !accepted && d.io.ingress(src).ready.peek().litToBoolean
          val got = stepAndCheck(dst, expected)
          d.clock.step()
          if (fire) {
            accepted = true
            d.io.ingress(src).valid.poke(false.B)
          }
          if (got) delivered = true
          cycles += 1
        }
        assert(accepted, s"no ingress handshake for $src -> $dst")
        assert(delivered, s"no delivery for $src -> $dst after $cycles cycles")
        d.clock.step(5)
      }

      for (src <- 0 until n; dst <- 0 until n) {
        transact(src, dst, src * n + dst + 1)
      }

      for (e <- 0 until n) d.io.egress(e).ready.poke(false.B)
      val packetSrc = 0
      val packetDst = n - 1
      val packet = (0 to SelectedGec.depth).map { index =>
        val kind = if (index == 0) 0 else if (index == SelectedGec.depth) 2 else 1
        flit(packetSrc, packetDst, kind, sequence = 2001 + index, inputVc = 1)
      }
      packet.foreach(raw => inject(packetSrc, raw))
      var waitCycles = 0
      while (!d.io.egress(packetDst).valid.peek().litToBoolean && waitCycles < 1000) {
        for (e <- 0 until n if e != packetDst) {
          assert(!d.io.egress(e).valid.peek().litToBoolean, s"stalled packet escaped to endpoint $e")
        }
        d.clock.step()
        waitCycles += 1
      }
      assert(d.io.egress(packetDst).valid.peek().litToBoolean, "packet did not reach stalled egress")
      val stalled = d.io.egress(packetDst).bits.peek().litValue
      assert(stalled == (packet.head & preserveMask))
      for (_ <- 0 until 6) {
        for (e <- 0 until n if e != packetDst) {
          assert(!d.io.egress(e).valid.peek().litToBoolean, s"stalled packet escaped to endpoint $e")
        }
        d.clock.step()
        d.io.egress(packetDst).valid.expect(true.B)
        d.io.egress(packetDst).bits.expect(stalled.U(width.W))
      }
      d.io.egress(packetDst).ready.poke(true.B)
      val received = mutable.ArrayBuffer.empty[BigInt]
      var drainCycles = 0
      while (received.size < packet.size && drainCycles < 1000) {
        if (d.io.egress(packetDst).valid.peek().litToBoolean) {
          received += d.io.egress(packetDst).bits.peek().litValue
        }
        for (e <- 0 until n if e != packetDst) {
          assert(!d.io.egress(e).valid.peek().litToBoolean, s"packet escaped to endpoint $e")
        }
        d.clock.step()
        drainCycles += 1
      }
      assert(received.toSeq == packet.map(_ & preserveMask), s"packet mismatch: $received")
      for (e <- 0 until n) d.io.egress(e).ready.poke(true.B)
      d.clock.step(8)

      val contenders = Seq(0, 6, 12, 18)
      val contentionDst = n - 1
      val expected = contenders.zipWithIndex.map { case (src, i) =>
        val raw = flit(src, contentionDst, kind = 3, sequence = 3000 + i, inputVc = 0)
        src -> (raw & preserveMask)
      }.toMap
      contenders.foreach { src =>
        val raw = expected(src) | (BigInt(contentionDst) << SelectedGec.destLsb) |
          (BigInt(3) << SelectedGec.typeLsb)
        d.io.ingress(src).bits.poke(raw.U(width.W))
        d.io.ingress(src).valid.poke(true.B)
      }
      val accepted = mutable.Set.empty[Int]
      val delivered = mutable.Set.empty[BigInt]
      var contentionCycles = 0
      while ((accepted.size < contenders.size || delivered.size < contenders.size) && contentionCycles < 2000) {
        val fires = contenders.filter(src => !accepted(src) && d.io.ingress(src).ready.peek().litToBoolean)
        for (e <- 0 until n if d.io.egress(e).valid.peek().litToBoolean) {
          assert(e == contentionDst, s"contending packet delivered to endpoint $e")
          val actual = d.io.egress(e).bits.peek().litValue
          assert(expected.values.toSet(actual), f"unexpected or duplicate contention payload 0x$actual%x")
          assert(!delivered(actual), f"duplicate contention payload 0x$actual%x")
          delivered += actual
        }
        d.clock.step()
        fires.foreach { src =>
          accepted += src
          d.io.ingress(src).valid.poke(false.B)
        }
        contentionCycles += 1
      }
      assert(accepted.size == contenders.size, s"only accepted ${accepted.size}/${contenders.size} contenders")
      assert(delivered.size == contenders.size, s"only delivered ${delivered.size}/${contenders.size} contenders")
      d.clock.step(10)
      for (slot <- 0 until diagnostics.freeCredits.length) {
        diagnostics.freeCredits(slot).expect(SelectedGec.depth.U)
        diagnostics.ownedOutputVcs(slot).expect(false.B)
      }
      for (slot <- 0 until diagnostics.inputOccupancy.length) {
        diagnostics.inputOccupancy(slot).expect(0.U)
      }

      val resetSrc = 1
      val resetDst = n - 1
      d.io.egress(resetDst).ready.poke(false.B)
      val resetFlit = flit(resetSrc, resetDst, kind = 3, sequence = 4001, inputVc = 0)
      inject(resetSrc, resetFlit) // One accepted flit is deliberately flushed by reset.
      var resetWait = 0
      while (!d.io.egress(resetDst).valid.peek().litToBoolean && resetWait < 1000) {
        d.clock.step()
        resetWait += 1
      }
      assert(d.io.egress(resetDst).valid.peek().litToBoolean, "reset stimulus never reached the stalled egress")
      d.reset.poke(true.B)
      d.clock.step(2)
      d.reset.poke(false.B)
      d.io.egress(resetDst).ready.poke(true.B)
      d.clock.step(2)
      for (e <- 0 until n) d.io.egress(e).valid.expect(false.B)
      for (wire <- 0 until diagnostics.wireFire.length) diagnostics.wireFire(wire).expect(false.B)
      for (slot <- 0 until diagnostics.freeCredits.length) {
        diagnostics.freeCredits(slot).expect(SelectedGec.depth.U)
        diagnostics.ownedOutputVcs(slot).expect(false.B)
      }
      for (slot <- 0 until diagnostics.inputOccupancy.length) {
        diagnostics.inputOccupancy(slot).expect(0.U)
      }
    }
  }
}
