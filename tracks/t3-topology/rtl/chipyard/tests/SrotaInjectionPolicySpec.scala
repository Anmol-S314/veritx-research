package veritx.chipyard

import chisel3._
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec

class SrotaInjectionPolicySpec extends AnyFlatSpec with ChiselScalatestTester {
  behavior of "SROTA injection policy"

  private val base = SrotaFiuConfig(k = 4, sources = 2, entries = 64,
    epochCycles = 1024, paths = 3, threshold = 8)

  private def clear(d: SrotaInjectionPolicy): Unit = {
    d.io.flow.valid.poke(false.B)
    d.io.flow.bits.source.poke(0.U)
    d.io.flow.bits.destination.poke(0.U)
    d.io.flow.bits.trafficClass.poke(0.U)
    d.io.decision.ready.poke(false.B)
    for (i <- 0 until 4) {
      d.io.rowLoads(i).poke(0.U)
      d.io.columnLoads(i).poke(0.U)
    }
    d.io.randomWord.poke(0.U)
  }

  it should "choose the less-loaded column shape" in {
    test(new SrotaInjectionPolicy(base)) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.destination.poke(1.U) // x = 1, y = 0
      d.io.columnLoads(1).poke(6.U) // rowLoad
      d.io.rowLoads(0).poke(2.U) // colLoad
      d.clock.step()
      d.io.decision.valid.expect(true.B)
      d.io.decision.bits.shape.expect(1.U)
      d.io.decision.bits.cacheHit.expect(false.B)
    }
  }

  it should "choose the row shape on lower row load or a tie" in {
    test(new SrotaInjectionPolicy(base)) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.destination.poke(1.U)
      d.io.columnLoads(1).poke(2.U)
      d.io.rowLoads(0).poke(6.U)
      d.clock.step()
      d.io.decision.valid.expect(true.B)
      d.io.decision.bits.shape.expect(0.U)

      d.io.flow.valid.poke(false.B)
      d.io.decision.ready.poke(true.B)
      d.clock.step()

      d.io.decision.ready.poke(false.B)
      d.io.flow.valid.poke(true.B)
      d.io.columnLoads(1).poke(4.U)
      d.io.rowLoads(0).poke(4.U)
      d.clock.step()
      d.io.decision.bits.shape.expect(0.U)
    }
  }

  it should "use a Valiant intermediate when both dimensions are congested" in {
    test(new SrotaInjectionPolicy(base.copy(paths = 7))) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.destination.poke(5.U) // x = 1, y = 1; srcRouter = 0
      d.io.rowLoads(1).poke(9.U)
      d.io.columnLoads(1).poke(9.U)
      d.io.randomWord.poke(2.U)
      d.io.flow.ready.expect(true.B)
      d.io.randomUsed.expect(true.B)
      d.clock.step()
      d.io.decision.valid.expect(true.B)
      d.io.decision.bits.shape.expect(2.U)
      d.io.decision.bits.intermediate.expect(2.U)
    }
  }

  it should "reject an intermediate equal to its source or destination router" in {
    test(new SrotaInjectionPolicy(base.copy(paths = 7))) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.destination.poke(5.U)
      d.io.rowLoads(1).poke(9.U)
      d.io.columnLoads(1).poke(9.U)

      d.io.randomWord.poke(0.U) // equals srcRouter
      d.io.flow.ready.expect(false.B)
      d.io.decision.valid.expect(false.B)
      d.io.randomUsed.expect(true.B)

      d.io.randomWord.poke(5.U) // equals destRouter
      d.io.flow.ready.expect(false.B)

      d.io.randomWord.poke(3.U)
      d.io.flow.ready.expect(true.B)
      d.clock.step()
      d.io.decision.bits.intermediate.expect(3.U)
    }
  }

  it should "force a declared island column to the column shape" in {
    test(new SrotaInjectionPolicy(base.copy(islandColumns = Set(1)))) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.destination.poke(5.U) // x = 1
      d.io.rowLoads(1).poke(9.U)
      d.io.columnLoads(1).poke(0.U)
      d.clock.step()
      d.io.decision.valid.expect(true.B)
      d.io.decision.bits.shape.expect(1.U)
    }
  }

  it should "reuse the cached shape and intermediate for a same-epoch flow" in {
    test(new SrotaInjectionPolicy(base.copy(forcedShape = 0))) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.source.poke(1.U)
      d.io.flow.bits.destination.poke(6.U)
      d.io.flow.bits.trafficClass.poke(3.U)
      d.io.randomWord.poke(7.U)
      d.clock.step()
      d.io.decision.valid.expect(true.B)
      d.io.decision.bits.cacheHit.expect(false.B)
      d.io.decision.bits.shape.expect(0.U)
      d.io.decision.bits.intermediate.expect(7.U)
      val hash = d.io.decision.bits.flowHash.peek().litValue

      d.io.flow.valid.poke(false.B)
      d.io.decision.ready.poke(true.B)
      d.clock.step()

      d.io.decision.ready.poke(false.B)
      d.io.flow.valid.poke(true.B)
      d.io.randomWord.poke(9.U)
      d.clock.step()
      d.io.decision.valid.expect(true.B)
      d.io.decision.bits.cacheHit.expect(true.B)
      d.io.decision.bits.shape.expect(0.U)
      d.io.decision.bits.intermediate.expect(7.U)
      assert(d.io.decision.bits.flowHash.peek().litValue == hash)
    }
  }

  it should "skip intermediate sampling when a non-Valiant shape is forced" in {
    test(new SrotaInjectionPolicy(base.copy(forcedShape = 1))) { d =>
      clear(d)
      d.io.flow.valid.poke(true.B)
      d.io.flow.bits.destination.poke(5.U)
      d.io.randomWord.poke(0.U) // would be inadmissible if sampling were required
      d.io.randomUsed.expect(false.B)
      d.io.flow.ready.expect(true.B)
      d.clock.step()
      d.io.decision.bits.shape.expect(1.U)
    }
  }
}
