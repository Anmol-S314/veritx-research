"""Evidence-first capability archaeology — structural consistency.

PART 20 of the archaeology work order. These are NOT brittle line-count or
branch-SHA checks: they assert that the ledger is structurally honest, so a
future edit cannot quietly turn a "backend-only" capability into a bare
"SUPPORTED", or assert a measured capability without citing the artifact.

Nothing here depends on a remote branch being present.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[4]
DOC = REPO / "docs/product/EVIDENCE-FIRST-CAPABILITY-ARCHAEOLOGY.md"
LEDGER = REPO / "docs/product/capability-archaeology.yaml"

@pytest.fixture(scope="module")
def ledger():
    return load_ledger_strict(LEDGER)

class DuplicateKeyError(ValueError):
    """A machine-readable ledger may not contain duplicate mapping keys."""

def _strict_loader():
    """A SafeLoader that FAILS on duplicate mapping keys.

    `yaml.safe_load()` silently keeps the later value, so the CDC record once
    defined EXECUTED_ANYWHERE and MEASURED_ANYWHERE twice and every
    "all 13 axes present" check still passed. Silent acceptance is the bug.
    """
    class _Loader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise DuplicateKeyError(
                    f"duplicate key {key!r} at line "
                    f"{key_node.start_mark.line + 1}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    _Loader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
    return _Loader

def load_ledger_strict(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=_strict_loader())

def test_ledger_has_no_duplicate_mapping_keys():
    """The law: NO DUPLICATE KEY MAY EXIST IN THE MACHINE-READABLE LEDGER."""
    load_ledger_strict(LEDGER)

def test_strict_loader_actually_fails_on_duplicate_keys(tmp_path):
    """Proof the loader is strict — a synthetic duplicate must raise, or the
    test above is vacuous."""
    bad = tmp_path / "dup.yaml"
    bad.write_text("a: 1\nb: 2\na: 3\n")
    with pytest.raises(DuplicateKeyError):
        load_ledger_strict(bad)
    bad2 = tmp_path / "dup2.yaml"
    bad2.write_text("capabilities:\n  - id: X\n    MEASURED_ANYWHERE: A\n"
                    "    MEASURED_ANYWHERE: B\n")
    with pytest.raises(DuplicateKeyError):
        load_ledger_strict(bad2)

def test_strict_loader_agrees_with_safe_load_on_a_valid_document(tmp_path):
    good = tmp_path / "ok.yaml"
    good.write_text("a: 1\nb:\n  - c: 2\n")
    assert load_ledger_strict(good) == yaml.safe_load(good.read_text())

def test_the_intent_and_artifact_layers_are_separate_axes(ledger):
    """PHASE B.2 §9: one CANONICAL_REPRESENTATION field could not distinguish
    "the design can be DECLARED" from "the physical fabric can be DERIVED".
    GEC's four modes and fat-tree have a canonical INTENT with no canonical
    physical ARTIFACT, which the old single field could not express."""
    for cap in ledger["capabilities"]:
        assert "CANONICAL_INTENT" in cap, cap["id"]
        assert "CANONICAL_PHYSICAL_ARTIFACT" in cap, cap["id"]

def test_intent_and_artifact_are_independently_stated(ledger):
    """A record may have an intent and no artifact — the B.1 state — and that
    must be visible without reading prose in the OTHER field."""
    by_id = {c["id"]: c for c in ledger["capabilities"]}
    for cap_id in ("GEC-MECS", "GEC-HYBRID", "FAT-TREE"):
        cap = by_id[cap_id]
        assert str(cap["CANONICAL_INTENT"]).strip().upper().startswith("YES"),             cap_id
        assert str(cap["CANONICAL_PHYSICAL_ARTIFACT"]).strip().upper() \
            .startswith("NO"), cap_id

def test_flatfly_is_authorable_and_materializable(ledger):
    """The pre-B.1 claim (`CANONICAL_DERIVATION: NO — family is not
    AUTHORABLE`) is false: FlatFlyIntent declares it and MaterializedFamily.
    FLATFLY builds it."""
    cap = {c["id"]: c for c in ledger["capabilities"]}["FLATFLY"]
    assert str(cap["CANONICAL_INTENT"]).strip().upper().startswith("YES")
    assert str(cap["CANONICAL_PHYSICAL_ARTIFACT"]).strip().upper() \
        .startswith("YES")

def test_gec_subfamilies_are_independently_trackable(ledger):
    """One GEC row could not express mesh/express versus blocked MECS/hybrid."""
    ids = {c["id"] for c in ledger["capabilities"]}
    for cap_id in ("GEC-MESH", "GEC-EXPRESS", "GEC-MECS", "GEC-HYBRID"):
        assert cap_id in ids, cap_id

def test_every_record_answers_every_axis(ledger):
    """No collapsed SUPPORTED flag: every axis independently.

    PHASE B.2 §9 grew this from 13 to 15 by splitting the overloaded
    CANONICAL_REPRESENTATION into CANONICAL_INTENT and
    CANONICAL_PHYSICAL_ARTIFACT.
    """
    required = ledger["fields"]
    assert len(required) == 15
    assert "CANONICAL_INTENT" in required
    assert "CANONICAL_PHYSICAL_ARTIFACT" in required
    for cap in ledger["capabilities"]:
        missing = [f for f in required if f not in cap]
        assert not missing, f"{cap['id']} missing {missing}"
        for f in required:
            assert str(cap[f]).strip(), f"{cap['id']}.{f} is empty"

def test_no_record_uses_unsupported_as_its_only_classification(ledger):
    allowed = set(ledger["classifications"])
    for cap in ledger["capabilities"]:
        cls = cap["classifications"]
        assert cls, f"{cap['id']} has no classification"
        assert set(cls) <= allowed, f"{cap['id']} has unknown classes {set(cls) - allowed}"
        assert "unsupported" not in " ".join(cls).lower()

def test_classification_vocabulary_is_declared_and_used(ledger):
    declared = set(ledger["classifications"])
    used = {c for cap in ledger["capabilities"] for c in cap["classifications"]}
    assert used <= declared
    for must in ("CURRENT_CANONICAL", "CURRENT_BACKEND_ONLY",
                 "HISTORICAL_EXECUTABLE", "HISTORICAL_MEASURED",
                 "DOC_STALE", "TRULY_ABSENT"):
        assert must in declared

def test_every_classification_has_an_exact_definition(ledger):
    defs = ledger.get("classification_definitions") or {}
    for cls in ledger["classifications"]:
        assert cls in defs, f"{cls} has no definition"
        assert len(defs[cls].split()) >= 8, f"{cls} definition is a stub"

def test_current_canonical_definition_excludes_mere_presence(ledger):
    d = ledger["classification_definitions"]["CURRENT_CANONICAL"].lower()
    assert "authority model" in d
    assert "does not mean" in d and "repository" in d

def test_current_canonical_requires_a_canonical_representation(ledger):
    """A CURRENT_CANONICAL record may not say CANONICAL_REPRESENTATION is
    NO or N/A. PARTIAL must name the canonical portion that exists."""
    for cap in ledger["capabilities"]:
        if "CURRENT_CANONICAL" not in cap["classifications"]:
            continue
        rep = str(cap["CANONICAL_REPRESENTATION"]).strip()
        assert not rep.upper().startswith(("NO", "N/A")), (
            f"{cap['id']} is CURRENT_CANONICAL but CANONICAL_REPRESENTATION "
            f"is {rep!r}")
        if rep.upper().startswith("PARTIAL"):
            assert len(rep.split()) >= 6, (
                f"{cap['id']} claims PARTIAL canonical representation "
                "without naming which portion exists")

def test_reclassified_records_are_no_longer_current_canonical(ledger):
    """The three records whose own fields contradicted CURRENT_CANONICAL."""
    for cid in ("NOC-ENERGY", "RTL-VALIDATION", "UVM-SVA"):
        cap = next(c for c in ledger["capabilities"] if c["id"] == cid)
        assert "CURRENT_CANONICAL" not in cap["classifications"], \
            f"{cid} is still CURRENT_CANONICAL"

_IMPLEMENTATION_ONLY = (".py", ".cpp", ".hpp", ".h", ".yaml", ".cfg", ".sh",
                       ".patch", ".sv", ".ts")
_RESULT_LIKE = (".md", ".json", ".csv", ".txt", ".xlsx")

def _cites(cap) -> str:
    return " ".join(str(v) for v in cap.values()) + " " + \
        " ".join(cap.get("evidence") or []) + " " + \
        " ".join(cap.get("historical_evidence") or [])

def test_claimed_implementations_cite_a_source_path(ledger):
    """A YES/PARTIAL implementation must name a real path."""
    path_re = re.compile(r"[A-Za-z0-9_./-]+\.(py|cpp|hpp|h|md|yaml|json|cfg|sh|patch|sv|ts)")
    for cap in ledger["capabilities"]:
        impl = str(cap["IMPLEMENTED_ANYWHERE"])
        if impl.startswith("YES") or impl.startswith("PARTIAL"):
            assert path_re.search(_cites(cap)), (
                f"{cap['id']} claims implementation without citing a path")
        elif impl.startswith("NO"):
            pass
        else:
            assert impl.startswith("N/A"), \
                f"{cap['id']}: odd IMPLEMENTED_ANYWHERE {impl!r}"

def test_every_yes_measurement_cites_result_evidence(ledger):
    """PART C law — applies to EVERY record, not only HISTORICAL_MEASURED.
    A script or implementation file proves executable POTENTIAL, never
    MEASURED."""
    for cap in ledger["capabilities"]:
        measured = str(cap["MEASURED_ANYWHERE"]).strip()
        if not measured.upper().startswith("YES"):
            continue
        cited = _cites(cap)
        assert any(t in cited for t in _RESULT_LIKE), (
            f"{cap['id']} claims MEASURED_ANYWHERE={measured!r} but cites no "
            "result artifact (only implementation/script paths)")

def test_historical_evidence_is_commit_qualified(ledger):
    """A historical citation must name a commit, so it can be re-found."""
    for cap in ledger["capabilities"]:
        for h in cap.get("historical_evidence") or []:
            assert re.match(r"^[0-9a-f]{7,40}[:/]", h), (
                f"{cap['id']} historical_evidence {h!r} is not commit-qualified")

def test_every_evidence_path_exists(ledger):
    """`evidence` paths are HEAD artifacts and must exist."""
    for cap in ledger["capabilities"]:
        for p in cap.get("evidence") or []:
            assert (REPO / p).exists(), \
                f"{cap['id']} cites a non-existent path: {p}"

def test_every_record_names_a_missing_bridge_or_explicitly_none(ledger):
    for cap in ledger["capabilities"]:
        mb = str(cap["MISSING_BRIDGE"]).strip()
        assert mb, f"{cap['id']} has an empty MISSING_BRIDGE"
        assert mb.lower() != "unknown"

def test_backend_only_capabilities_name_a_layer_not_a_verdict(ledger):
    """'GEC unsupported' is forbidden. A backend-only record must name the
    MISSING layer."""
    for cap in ledger["capabilities"]:
        if "CURRENT_BACKEND_ONLY" in cap["classifications"]:
            mb = str(cap["MISSING_BRIDGE"]).lower()
            assert "unsupported" not in mb
            assert len(mb.split()) >= 3, f"{cap['id']} bridge too vague: {mb!r}"

def test_no_truly_absent_record_without_search_scope(ledger):
    for cap in ledger["capabilities"]:
        if "TRULY_ABSENT" in cap["classifications"]:
            cited = _cites(cap).lower()
            assert "search" in cited or "searched" in cited, (
                f"{cap['id']} claims TRULY_ABSENT without recording search scope")

def test_document_states_the_evidence_order(ledger):
    doc = DOC.read_text()
    assert "EVIDENCE ORDER" in doc
    assert "Source beats prose" in doc
    for ref in ("p1b/verified-evaluation", "integration/p1-product",
                "epic/booksim-forward-port"):
        assert ref in doc

def test_document_carries_the_registry_contradiction_section():
    doc = DOC.read_text()
    assert "REGISTRY CLAIMS THAT DO NOT MATCH EXECUTABLE EVIDENCE" in doc
    for target in ("topology-family-registry.yaml", "capability-registry.yaml",
                   "feature-reclamation-registry.yaml",
                   "FEATURE-RECLAMATION-AUDIT.md",
                   "FEATURE-RECLAMATION-AMENDMENT.md",
                   "CAPABILITY-MATRIX.md"):
        assert target in doc, f"{target} not named in the contradiction report"

def test_document_classification_counts_match_the_ledger(ledger):
    """The doc's count table must equal the ledger, so the two cannot drift."""
    doc = DOC.read_text()
    section = doc.split("## 6. CLASSIFICATION COUNTS")[1].split("## 7.")[0]
    counts = {c: sum(1 for cap in ledger["capabilities"]
                     if c in cap["classifications"])
              for c in ledger["classifications"]}
    for cls, n in counts.items():
        row = re.search(rf"\|\s*{cls}\s*\|\s*(\d+)\s*\|", section)
        assert row, f"{cls} missing from the doc count table"
        assert int(row.group(1)) == n, (
            f"{cls}: doc says {row.group(1)}, ledger says {n}")

def test_document_records_the_mecs_power_invalidity(ledger):
    doc = DOC.read_text()
    assert "_md_chan" in doc
    assert "INVALID/INCOMPLETE" in doc
    cap = next(c for c in ledger["capabilities"] if c["id"] == "BOOKSIM-NATIVE-POWER")
    assert "_md_chan" in cap["MISSING_BRIDGE"]

def test_document_does_not_claim_multicast_json_is_capability():
    doc = DOC.read_text()
    assert "no consumer" in doc.lower()
    assert "is not an executable capability" in doc

def test_counts_are_scoped_to_the_audited_records():
    doc = DOC.read_text()
    assert "these 26 audited records" in doc
    assert "Counts are OUTPUTS" in doc

def test_truly_absent_scope_law_is_explicit():
    """`TRULY_ABSENT = 0` must never read as 'VERITX has no absent
    capabilities'."""
    doc = DOC.read_text()
    assert "does **not** mean \"VERITX has no" in doc
    assert "strict TRULY_ABSENT definition" in doc

def test_document_records_the_metric_population_split():
    doc = DOC.read_text()
    assert "LATENCY METRIC AUTHORITY" in doc
    assert "sim.trace_request_latency.avg_cycles" in doc
    assert "_plat_stats" in doc and "_all_latencies" in doc

def test_document_records_the_corrected_measurement_claims():
    doc = DOC.read_text()
    section = doc.split("### Measurement claims corrected in the seal pass")[1]
    for cid in ("Fat-tree/QTree/Tree4/Dragonfly", "Static MoE",
                "P2P + logical multicast", "Hardware multicast"):
        assert cid in section, f"{cid} not recorded as corrected"

def test_document_records_the_reclassifications():
    doc = DOC.read_text()
    section = doc.split("### Classification semantics")[1].split("### TRULY_ABSENT")[0]
    for cid in ("NoC energy", "RTL validation", "UVM/SVA"):
        assert cid in section, f"{cid} reclassification not recorded"

def test_every_yes_execution_claim_cites_durable_execution_evidence(ledger):
    """A source file or runnable script proves EXECUTABLE POTENTIAL, never
    EXECUTED. A YES execution claim needs a durable run record: a result
    artifact, evidence document, or a commit-qualified status/result."""
    for cap in ledger["capabilities"]:
        ex = str(cap["EXECUTED_ANYWHERE"]).strip()
        if not ex.upper().startswith("YES"):
            continue
        cited = _cites(cap)
        has_result_doc = any(t in cited for t in _RESULT_LIKE)
        has_commit_ref = bool(cap.get("historical_evidence"))
        assert has_result_doc or has_commit_ref, (
            f"{cap['id']} claims EXECUTED_ANYWHERE={ex!r} but cites no durable "
            "execution evidence (only implementation/script/test paths)")

def test_scripts_and_sources_alone_never_satisfy_the_execution_law():
    """Regression proof for the law itself: a record whose only citations are
    .py/.cpp/.sh must NOT be able to claim YES execution."""
    fake = {
        "id": "SYNTHETIC", "EXECUTED_ANYWHERE": "YES — it runs",
        "evidence": ["a.py", "b.cpp", "c.sh"], "MEASURED_ANYWHERE": "NO",
    }
    cited = _cites(fake)
    assert not any(t in cited for t in _RESULT_LIKE)
    assert not fake.get("historical_evidence")

def test_executable_potential_wording_is_used_where_execution_is_unproven(ledger):
    """The records downgraded in this pass must say so explicitly."""
    for cid in ("ADAPTIVE-ROUTING", "PIM", "QTREE", "TREE4", "NOC-ENERGY",
                "BOOKSIM-NATIVE-POWER", "RTL-VALIDATION", "CDC"):
        cap = next(c for c in ledger["capabilities"] if c["id"] == cid)
        ex = str(cap["EXECUTED_ANYWHERE"]).upper()
        assert not ex.startswith("YES"), f"{cid} still claims YES execution"
        assert ("NOT PROVEN" in ex or "POTENTIAL" in ex or "TESTED" in ex), \
            f"{cid} does not state its execution status precisely: {ex!r}"

def test_p2p_record_states_tested_lowering_not_execution(ledger):
    cap = next(c for c in ledger["capabilities"]
               if c["id"] == "P2P-LOGICAL-MULTICAST")
    assert "TESTED LOWERING" in cap["EXECUTED_ANYWHERE"]
    assert "NOT PROVEN" in cap["MEASURED_ANYWHERE"]

def test_in_process_primitives_are_labelled_as_tested_primitives(ledger):
    for cid in ("CANDIDATE-PROMOTION", "EVIDENCE-REUSE", "SEARCH-COMPLETENESS",
                "WAVE-E-METRICS"):
        cap = next(c for c in ledger["capabilities"] if c["id"] == cid)
        assert "TESTED PRIMITIVE" in cap["EXECUTED_ANYWHERE"], cid

def test_historical_refs_use_full_sha_where_feasible(ledger):
    """A durable citation must be a full 40-char SHA so it cannot collide and
    can be fetched by SHA."""
    for cap in ledger["capabilities"]:
        for h in cap.get("historical_evidence") or []:
            sha = h.split(":")[0]
            assert len(sha) == 40, (
                f"{cap['id']} historical ref {h!r} is not a full SHA")

def test_no_historical_ref_is_an_unreachable_local_sha(ledger):
    """Every cited SHA must exist locally AND be contained by at least one
    ref, so a claim cannot rest on a dangling object in one clone."""
    import subprocess
    for cap in ledger["capabilities"]:
        for h in cap.get("historical_evidence") or []:
            sha = h.split(":")[0]
            t = subprocess.run(["git", "cat-file", "-t", sha], cwd=REPO,
                               capture_output=True, text=True)
            if t.returncode != 0:
                pytest.skip(f"{sha[:12]} not present in this clone")
            refs = subprocess.run(
                ["git", "for-each-ref", "--contains", sha,
                 "--format=%(refname)"], cwd=REPO,
                capture_output=True, text=True).stdout.strip()
            assert refs, (
                f"{cap['id']} cites {sha[:12]} which is UNREACHABLE from any "
                "ref — a dangling object is not repository evidence")

def test_historical_refs_point_at_real_paths_not_directories(ledger):
    """A directory such as `comm/topics/status` is not a record. Cite the
    file that actually contains the result."""
    import subprocess
    for cap in ledger["capabilities"]:
        for h in cap.get("historical_evidence") or []:
            sha, _, path = h.partition(":")
            if not path:
                continue
            if path.endswith("/"):
                raise AssertionError(f"{cap['id']} cites a directory: {h!r}")
            t = subprocess.run(["git", "cat-file", "-t", f"{sha}:{path}"],
                               cwd=REPO, capture_output=True, text=True)
            if t.returncode != 0:
                pytest.skip(f"{sha[:12]}:{path} not present in this clone")
            assert t.stdout.strip() == "blob", (
                f"{cap['id']} historical ref {h!r} is not a file")

def test_qtree_and_tree4_do_not_claim_the_comparison_script(ledger):
    """run_full_comparison.py runs CMesh/Flatfly/Fat-tree/Dragonfly/Torus.
    It does NOT run qtree or tree4, so neither may cite it as evidence."""
    for cid in ("QTREE", "TREE4"):
        cap = next(c for c in ledger["capabilities"] if c["id"] == cid)
        cited = " ".join([
            str(cap["EXECUTED_ANYWHERE"]), str(cap["MEASURED_ANYWHERE"]),
            str(cap["IMPLEMENTED_ANYWHERE"]),
            " ".join(cap.get("evidence") or []),
            " ".join(cap.get("historical_evidence") or []),
        ])
        assert "run_full_comparison" not in cited, (
            f"{cid} cites run_full_comparison.py as evidence, but that script "
            "does not run it")
        assert "full_topology_comparison.xlsx" not in cited, (
            f"{cid} cites the comparison workbook, which has no {cid} rows")

def test_fat_tree_and_dragonfly_cite_the_measured_workbook(ledger):
    for cid in ("FAT-TREE", "DRAGONFLY"):
        cap = next(c for c in ledger["capabilities"] if c["id"] == cid)
        assert "full_topology_comparison.xlsx" in _cites(cap), cid
        assert cap.get("historical_evidence"), cid

def test_the_four_topologies_are_separate_records(ledger):
    ids = {c["id"] for c in ledger["capabilities"]}
    for cid in ("FAT-TREE", "DRAGONFLY", "QTREE", "TREE4"):
        assert cid in ids, f"{cid} missing"
    assert "FAT-TREE-QTREE-TREE4-DRAGONFLY" not in ids, "combined record remains"
