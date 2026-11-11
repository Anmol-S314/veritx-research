package constellation.veritx

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import scala.jdk.CollectionConverters._

/** Single entry point for all fourteen research targets. No fallback emitter. */
object AllTopologyRtlExport {
  private val exporters: Seq[(String, Array[String] => Unit)] = Seq(
    "mesh8x8" -> CatalogRtlMeshExport.main _,
    "torus8x8" -> CatalogRtlTorusExport.main _,
    "cmesh" -> CatalogRtlCmeshExport.main _,
    "ring" -> CatalogRtlRingExport.main _,
    "gec_mecs" -> CatalogRtlGecMecsExport.main _,
    "fly64" -> CatalogRtlFly64Export.main _,
    "qtree" -> CatalogRtlQTreeExport.main _,
    "tree4" -> CatalogRtlTree4Export.main _,
    "flatfly" -> CatalogRtlFlatFlyExport.main _,
    "srota8x8" -> CatalogRtlSrotaExport.main _,
    "gec_hybrid" -> CatalogRtlHybridExport.main _,
    "fattree" -> CatalogRtlFattreeExport.main _,
    "dragonflynew" -> CatalogRtlDragonflyExport.main _,
    "kncube" -> CatalogRtlKNCubeExport.main _)
  val topologyIds: Seq[String] = exporters.map(_._1)
  require(topologyIds.distinct.size == 14)

  def main(args: Array[String]): Unit = {
    if (args.sameElements(Array("--list"))) {
      topologyIds.foreach(println)
      return
    }
    require(args.length >= 2,
      "usage: AllTopologyRtlExport <topologyId> <freshOutDir> [exporter arguments]; or --list")
    val id = args(0)
    val exporter = exporters.toMap.getOrElse(id,
      throw new IllegalArgumentException(s"unknown topology $id; choose ${topologyIds.mkString(",")}"))
    val out = Paths.get(args(1)).toAbsolutePath.normalize
    require(!out.toString.contains("/transitions/") &&
      !out.toString.contains("/contracts/candidate_exports/"), "refusing sealed output")
    require(!Files.exists(out), s"output directory must be new: $out")
    // Each existing exporter owns its native topology, VC and route semantics.
    // Extra arguments are explicit; no geometry or VC substitution occurs here.
    exporter(Array(out.toString) ++ args.drop(2))
    val stream = Files.walk(out)
    val emitted = try stream.iterator.asScala.exists { p =>
      Files.isRegularFile(p) && (p.toString.endsWith(".v") || p.toString.endsWith(".sv"))
    } finally stream.close()
    require(emitted, s"$id returned without producing RTL")
    val receipt = s"""{"schema":"veritx/all-topology-rtl/1","topology_id":"$id","scope":"RESEARCH_PROFILE","simulation":"NOT_RUN","qualification":"NOT_QUALIFIED","matches_selected_project":false,"final_implementation":false}"""
    Files.write(out.resolve("export-receipt.json"), receipt.getBytes(StandardCharsets.UTF_8))
  }
}
