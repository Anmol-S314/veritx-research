package veritx.chipyard

import chisel3._

/** Simulation assertions are not synthesizable cells. The synthesis emitter
  * sets `veritx.synthesize=1`; every other build keeps the checks.
  *
  * Both arguments are *by-name*.  That matters for elaboration cost: when the
  * check is disabled the condition expression is never evaluated, so the
  * hardware it would have built is never constructed.  With a by-value
  * parameter Scala evaluates `PopCount(...)`/`VecInit(...)` before `apply`
  * runs, the discarded expression still leaves its nodes in the FIRRTL IR,
  * and on the selected 81-router shape those dead nodes were 16.7 % of one
  * router body (3.5 MB of 21.1 MB) even though no assertion was emitted.
  */
object SynthAssert {
  private def enabled: Boolean =
    !sys.props.get("veritx.synthesize").contains("1")

  def apply(cond: => Bool): Unit = if (enabled) chisel3.assert(cond)
  def apply(cond: => Bool, msg: => String): Unit = if (enabled) chisel3.assert(cond, msg)
}
