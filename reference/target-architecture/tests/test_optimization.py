from fractions import Fraction
from veritx_dse.optimization.definition import OptimizationDefinition,Parameter,Objective
from veritx_dse.optimization.search import canonical_assignments
from veritx_dse.optimization.result import OptimizationResult,CandidateResult


def test_search_order_and_pareto_are_derived():
    d=OptimizationDefinition((Parameter("width",(256,64,128)),),(Objective("latency","MIN"),))
    expected=sorted([256,64,128], key=lambda x: __import__("json").dumps(x,sort_keys=True,separators=(",",":")))
    assert [x["width"] for x in canonical_assignments(d)]==expected
    r=OptimizationResult(d.definition_id(),
        (CandidateResult("a",(Fraction(3),)),CandidateResult("b",(Fraction(2),)),CandidateResult("c",(Fraction(4),))),
        ("MIN",))
    assert r.frontier()==("b",)
