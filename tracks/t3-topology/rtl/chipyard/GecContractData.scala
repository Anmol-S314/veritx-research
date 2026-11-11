package veritx.chipyard

import java.io.{ByteArrayInputStream, DataInputStream}
import java.security.MessageDigest

final case class GecWireData(src: Int, taps: Vector[Int], width: Int, latency: Int)
final case class GecContractData(routers: Int, vcs: Int, width: Int, depth: Int,
    endpoints: Vector[Int], wires: Vector[GecWireData],
    routes: Vector[Vector[(Int, Int, Int)]])

object GecContractData {
  private val Magic = 0x56474531

  def load(resource: String, expectedSha: String): GecContractData = {
    val stream = Option(getClass.getResourceAsStream(resource)).getOrElse(
      throw new IllegalArgumentException(s"missing compiled GEC data: $resource"))
    val bytes = try stream.readAllBytes() finally stream.close()
    val actual = MessageDigest.getInstance("SHA-256").digest(bytes)
      .map(b => f"${b & 0xff}%02x").mkString
    require(actual == expectedSha, "compiled GEC binary identity mismatch")
    val input = new DataInputStream(new ByteArrayInputStream(bytes))
    def int(): Int = input.readInt()
    def count(max: Int): Int = {
      val value = int()
      require(value >= 0 && value <= max, s"invalid GEC binary vector length: $value")
      value
    }
    def vector(max: Int): Vector[Int] = Vector.fill(count(max))(int())

    require(int() == Magic, "invalid compiled GEC binary version")
    val routers = int()
    val vcs = int()
    val width = int()
    val depth = int()
    require(routers > 0 && routers <= 100 && vcs > 0 && vcs <= 64 &&
      width >= 8 && width <= 1024 && depth > 0 && depth <= 256,
      "invalid compiled GEC dimensions")
    val endpoints = vector(256)
    require(endpoints.nonEmpty && endpoints.distinct.size == endpoints.size &&
      endpoints.forall(r => r >= 0 && r < routers),
      "compiled GEC endpoint map is invalid")
    val wires = Vector.fill(count(10000)) {
      val src = int()
      val wireWidth = int()
      val latency = int()
      val taps = vector(routers)
      require(src >= 0 && src < routers && wireWidth == width && latency > 0 &&
        taps.nonEmpty && taps.distinct.size == taps.size &&
        taps.forall(r => r >= 0 && r < routers), "invalid compiled GEC wire")
      GecWireData(src, taps, wireWidth, latency)
    }
    require(wires.nonEmpty, "compiled GEC contract has no shared wires")
    val routeRows = count(routers)
    require(routeRows == routers, "compiled GEC route row count mismatch")
    val routes = Vector.tabulate(routeRows) { sourceRouter =>
      val routeCount = count(routers)
      require(routeCount == routers, "compiled GEC route width mismatch")
      Vector.tabulate(routeCount) { destinationRouter =>
        val resource = int()
        val next = int()
        val vc = int()
        require(next >= 0 && next < routers && vc >= 0 && vc < vcs,
          "invalid compiled GEC route entry")
        if (resource == -1) require(sourceRouter == destinationRouter && next == sourceRouter,
          "local route does not terminate at its router")
        else require(resource >= 0 && resource < wires.size &&
          wires(resource).src == sourceRouter && wires(resource).taps.contains(next),
          "route does not match its shared wire/tap")
        (resource, next, vc)
      }
    }
    require(input.available() == 0, "trailing compiled GEC data")
    input.close()
    GecContractData(routers, vcs, width, depth, endpoints, wires, routes)
  }
}
