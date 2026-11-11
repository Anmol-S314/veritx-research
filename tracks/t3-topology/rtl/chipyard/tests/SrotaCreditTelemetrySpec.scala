package veritx.chipyard

import chisel3._
import chiseltest._
import org.scalatest.flatspec.AnyFlatSpec

class SrotaCreditTelemetrySpec extends AnyFlatSpec with ChiselScalatestTester {
  behavior of "SROTA credit telemetry"

  private def base(d: SrotaCreditTelemetry, k: Int, inputs: Int): Unit = {
    for (r <- 0 until k * k; p <- 0 until inputs) {
      d.io.occupancy(r)(p).poke(0.U)
      d.io.capacity(r)(p).poke(4.U)
    }
    for (r <- 0 until k * k) {
      d.io.enabled(r).poke(true.B)
      d.io.watermark(r).poke(false.B)
    }
  }

  it should "round each router to a nibble and average rows and columns" in {
    test(new SrotaCreditTelemetry(k = 2, inputs = 2, period = 1, latency = 0)) { d =>
      base(d, 2, 2)
      d.io.occupancy(0)(0).poke(1.U); d.io.capacity(0)(0).poke(2.U) // 8
      d.io.occupancy(1)(0).poke(2.U); d.io.capacity(1)(0).poke(4.U) // 8
      d.io.occupancy(2)(0).poke(3.U); d.io.capacity(2)(0).poke(4.U) // 11
      d.clock.step()
      d.io.rowLoads(0).expect(8.U)
      d.io.rowLoads(1).expect(5.U)
      d.io.columnLoads(0).expect(9.U)
      d.io.columnLoads(1).expect(4.U)
    }
  }

  it should "zero disabled routers and force watermark routers to full" in {
    test(new SrotaCreditTelemetry(k = 2, inputs = 2, period = 1, latency = 0)) { d =>
      base(d, 2, 2)
      d.io.occupancy(0)(0).poke(1.U); d.io.capacity(0)(0).poke(2.U)
      d.io.occupancy(1)(0).poke(2.U); d.io.capacity(1)(0).poke(4.U)
      d.io.occupancy(2)(0).poke(3.U); d.io.capacity(2)(0).poke(4.U)
      d.io.enabled(2).poke(false.B)
      d.io.watermark(3).poke(true.B)
      d.io.rowLoads(0).expect(8.U)
      d.io.rowLoads(1).expect(7.U)
      d.io.columnLoads(0).expect(4.U)
      d.io.columnLoads(1).expect(11.U)

      // Disabled takes precedence over the watermark bit.
      d.io.enabled(3).poke(false.B)
      d.io.rowLoads(1).expect(0.U)
      d.io.columnLoads(1).expect(4.U)
    }
  }

  it should "clamp a full router to fifteen and truncate the average" in {
    test(new SrotaCreditTelemetry(k = 2, inputs = 1, period = 1, latency = 0)) { d =>
      base(d, 2, 1)
      d.io.occupancy(0)(0).poke(1.U); d.io.capacity(0)(0).poke(1.U)
      d.io.rowLoads(0).expect(7.U)
      d.io.columnLoads(0).expect(7.U)
    }
  }

  it should "report zero for a router with zero capacity" in {
    test(new SrotaCreditTelemetry(k = 2, inputs = 1, period = 1, latency = 0)) { d =>
      base(d, 2, 1)
      for (r <- 0 until 4) {
        d.io.occupancy(r)(0).poke(3.U)
        d.io.capacity(r)(0).poke(0.U)
      }
      d.io.rowLoads(0).expect(0.U)
      d.io.rowLoads(1).expect(0.U)
      d.io.columnLoads(0).expect(0.U)
      d.io.columnLoads(1).expect(0.U)
    }
  }

  it should "publish at the configured latency and hold between samples" in {
    test(new SrotaCreditTelemetry(k = 2, inputs = 1, period = 4, latency = 1)) { d =>
      base(d, 2, 1)
      d.io.occupancy(0)(0).poke(1.U); d.io.capacity(0)(0).poke(2.U)
      d.io.rowLoads(0).expect(0.U) // sample not yet due
      d.clock.step()
      d.io.rowLoads(0).expect(4.U) // delayed sample publishes
      d.io.columnLoads(0).expect(4.U)
      d.io.rowLoads(1).expect(0.U)
      d.clock.step()
      d.io.rowLoads(0).expect(4.U) // held between samples
      d.clock.step()
      d.io.rowLoads(0).expect(4.U)
    }
  }
}
