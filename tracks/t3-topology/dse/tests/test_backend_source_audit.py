"""Wave B3.8a/e/f/g tests — site-gated source-drift guard.

Proves the closed-world audit stays closed PER READ SITE, including the
production path for INACTIVE_FOR_PROFILE fields: a second read of
`packet_size` in the same file, a new-file read, and a moved-method read
all fail under the REAL profile semantics (inactive membership is not
proof). Also covers receiver aliases, extra source extensions, site-level
gate attribution, and the embedded mirror read-site identity.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    prepare_booksim_standalone,
)
from veritx_dse.backend.booksim_profile import (  # noqa: E402
    BOOKSIM_STANDALONE_PROFILE,
)
from veritx_dse.backend.serving import (  # noqa: E402
    prepare_serving_booksim,
)
from veritx_dse.backend.source_audit import (  # noqa: E402
    GATED_FIELDS, GATED_READ_SITES, MECHANISM_JUSTIFICATIONS,
    GatedReadSite, SourceAuditError, audit_source_drift, parse_pin_gate,
    read_accounting, scan_config_reads, verify_gates, verify_site_gates,
)
from veritx_dse.core.paths import REPO  # noqa: E402

BOOKSIM_SRC = REPO / "third_party" / "booksim2" / "src"
MIRROR_SRC = (REPO / "third_party" / "astra-sim" / "extern"
              / "network_backend" / "booksim2" / "booksim2" / "src")


def _rendered_values(raw: str) -> dict[str, str]:
    out = {}
    for line in raw.splitlines():
        if " = " in line and line.endswith(";"):
            key, value = line.split(" = ", 1)
            out[key] = value[:-1]
    return out


class _EmptyProfile:
    def active_names(self):
        return frozenset()

    def inactive_names(self):
        return frozenset()


class _PacketSizeInactiveProfile:
    """Real-profile shape for the production-path test: packet_size is
    INACTIVE_FOR_PROFILE (not merely unregistered-gated)."""

    def active_names(self):
        return frozenset()

    def inactive_names(self):
        return frozenset({"packet_size"})


class _WatchOutInactiveProfile:
    def active_names(self):
        return frozenset()

    def inactive_names(self):
        return frozenset({"watch_out"})


def _tree(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "src"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = root / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


@pytest.fixture(scope="module")
def bundle():
    return make_bundle(build_chain())


class TestCurrentClosure:
    def test_every_read_occurrence_is_registered_or_declared(self):
        report = audit_source_drift(BOOKSIM_SRC)
        assert report.unregistered == (), report.unregistered
        assert report.uncovered_sites == (), report.uncovered_sites
        assert report.stale_gated == (), report.stale_gated
        assert report.stale_scope == (), report.stale_scope
        assert report.stale_registered == (), report.stale_registered

    def test_declared_sites_cover_every_non_active_occurrence(self):
        inactive = set(BOOKSIM_STANDALONE_PROFILE.inactive_names())
        assert inactive <= set(GATED_FIELDS)
        reads = scan_config_reads(BOOKSIM_SRC)
        registry = set(BOOKSIM_STANDALONE_PROFILE.active_names()) | inactive
        assert set(GATED_FIELDS) == inactive | (
            {r.field for r in reads} - registry)
        declared = {f: {s.path: s.occurrences for s in sites}
                    for f, sites in GATED_READ_SITES.items()}
        for read in reads:
            if read.field in registry:
                continue
            counts: dict[str, int] = {}
            for occ in read.occurrences:
                counts[occ.path] = counts.get(occ.path, 0) + 1
            assert counts == declared[read.field], read.field

    def test_every_site_has_explicit_gates_and_justifications(self):
        for field, sites in GATED_READ_SITES.items():
            assert sites, field
            for site in sites:
                assert site.gates, f"{field}@{site.path}"
                for gate in site.gates:
                    if parse_pin_gate(gate) is None:
                        assert gate in MECHANISM_JUSTIFICATIONS, (
                            field, gate)
                        assert MECHANISM_JUSTIFICATIONS[gate]

    def test_multi_mechanism_sites_are_distinguished(self):
        # k/n/c/xr are safe for different reasons at different sites; the
        # declaration must say which gate belongs to which site.
        expected = {
            "networks/cmesh.cpp": ("pin:topology=anynet",),
            "traffic.cpp": ("pattern_dispatch",),
            "veritx_embed.cpp": ("conditional_presence",),
        }
        for field in ("k", "n"):
            by_path = {s.path: s.gates for s in GATED_READ_SITES[field]}
            for path, gates in expected.items():
                assert by_path[path] == gates, (field, path)
        c_paths = {s.path: s.gates for s in GATED_READ_SITES["c"]}
        assert c_paths["veritx_embed.cpp"] == ("conditional_presence",)
        assert c_paths["networks/gec.cpp"] == ("pin:topology=anynet",)
        xr_paths = {s.path: s.gates for s in GATED_READ_SITES["xr"]}
        assert xr_paths["traffic.cpp"] == ("pattern_dispatch",)
        assert xr_paths["networks/cmesh.cpp"] == ("pin:topology=anynet",)

    def test_occurrence_accounting(self):
        accounting = read_accounting(BOOKSIM_SRC)
        assert accounting["unique_fields"] == len(
            BOOKSIM_STANDALONE_PROFILE.active_names()) + len(GATED_FIELDS)
        assert accounting["total_occurrences"] > accounting["unique_fields"]
        assert (accounting["registered_active_occurrences"]
                + accounting["registered_inactive_occurrences"]
                + accounting["unregistered_gated_occurrences"]
                == accounting["total_occurrences"])

    def test_packet_size_occurrences_are_pinned(self):
        sites = {s.path: s for s in GATED_READ_SITES["packet_size"]}
        assert sites["trafficmanager.cpp"].occurrences == 2


class TestInactiveProductionPath:
    """The real production branch: field in INACTIVE_FOR_PROFILE must
    still satisfy its declared read sites."""

    def _sites(self, occurrences=2):
        return {"packet_size": (GatedReadSite(
            "trafficmanager.cpp", occurrences,
            ("TrafficManager::Init",),
            ("trace_records",)),)}

    def test_expected_occurrences_pass(self, tmp_path):
        src = _tree(tmp_path, **{"trafficmanager.cpp": (
            "void TrafficManager::Init() {\n"
            "  int a = config.GetInt(\"packet_size\");\n"
            "  int b = config.GetInt(\"packet_size\");\n"
            "}\n")})
        report = audit_source_drift(
            src, profile=_PacketSizeInactiveProfile(),
            sites=self._sites())
        assert report.clean, report.uncovered_sites

    def test_same_file_extra_occurrence_fails(self, tmp_path):
        src = _tree(tmp_path, **{"trafficmanager.cpp": (
            "void TrafficManager::Init() {\n"
            "  int a = config.GetInt(\"packet_size\");\n"
            "  int b = config.GetInt(\"packet_size\");\n"
            "  int c = config.GetInt(\"packet_size\");\n"
            "}\n")})
        report = audit_source_drift(
            src, profile=_PacketSizeInactiveProfile(),
            sites=self._sites())
        assert any("3 occurrence(s), declared 2" in s
                   for s in report.uncovered_sites)

    def test_new_file_occurrence_fails(self, tmp_path):
        src = _tree(tmp_path, **{
            "trafficmanager.cpp": (
                "void TrafficManager::Init() {\n"
                "  int a = config.GetInt(\"packet_size\");\n"
                "  int b = config.GetInt(\"packet_size\");\n"
                "}\n"),
            "iq_router.cpp": (
                "void IQRouter::_RouteEvaluate() {\n"
                "  int c = config.GetInt(\"packet_size\");\n"
                "}\n")})
        report = audit_source_drift(
            src, profile=_PacketSizeInactiveProfile(),
            sites=self._sites())
        assert any("packet_size@iq_router.cpp" in s
                   for s in report.uncovered_sites)

    def test_wrong_method_fails(self, tmp_path):
        src = _tree(tmp_path, **{"trafficmanager.cpp": (
            "void TrafficManager::Other() {\n"
            "  int a = config.GetInt(\"packet_size\");\n"
            "  int b = config.GetInt(\"packet_size\");\n"
            "}\n")})
        report = audit_source_drift(
            src, profile=_PacketSizeInactiveProfile(),
            sites=self._sites())
        assert any("functions" in s for s in report.uncovered_sites)

    def test_second_inactive_field_same_attacks(self, tmp_path):
        sites = {"watch_out": (GatedReadSite(
            "trafficmanager.cpp", 1, ("TrafficManager::New",),
            ("diagnostic_only",)),)}
        src = _tree(tmp_path, **{"trafficmanager.cpp": (
            "void TrafficManager::New() {\n"
            "  string f = config.GetStr(\"watch_out\");\n"
            "}\n")})
        assert audit_source_drift(src, profile=_WatchOutInactiveProfile(),
                                  sites=sites).clean
        src = _tree(tmp_path / "b", **{"trafficmanager.cpp": (
            "void TrafficManager::New() {\n"
            "  string f = config.GetStr(\"watch_out\");\n"
            "}\n"
            "void TrafficManager::Other() {\n"
            "  string g = config.GetStr(\"watch_out\");\n"
            "}\n")})
        report = audit_source_drift(src, profile=_WatchOutInactiveProfile(),
                                    sites=sites)
        assert any("2 occurrence(s), declared 1" in s
                   for s in report.uncovered_sites)


class TestScanner:
    def test_catches_dot_arrow_and_receiver_aliases(self, tmp_path):
        src = _tree(tmp_path, **{"router.cpp": (
            'int a = config.GetInt("one");\n'
            'string b = config->GetStr("two");\n'
            'int c = cfg.GetInt("three");\n'
            'string d = configuration->GetStr("four");\n')})
        fields = {r.field for r in scan_config_reads(src)}
        assert fields == {"one", "two", "three", "four"}

    def test_catches_new_source_extensions(self, tmp_path):
        src = _tree(tmp_path, **{
            "router.cc": 'int a = cfg.GetInt("cc_field");\n',
            "router.h": 'int b = configuration->GetInt("h_field");\n',
            "router.ipp": 'int c = cfg.GetInt("ipp_field");\n'})
        fields = {r.field for r in scan_config_reads(src)}
        assert fields == {"cc_field", "h_field", "ipp_field"}

    def test_catches_multiline_calls(self, tmp_path):
        src = _tree(tmp_path, **{"router.cpp": (
            'int a = config.GetInt(\n    "one");\n'
            'string b = config->\n    GetStr("two");\n'
            'int c = cfg\n    .GetInt("three");\n')})
        fields = {r.field for r in scan_config_reads(src)}
        assert fields == {"one", "two", "three"}

    def test_new_unregistered_read_is_flagged(self, tmp_path):
        src = _tree(tmp_path, **{"iq_router.cpp":
                                 'int x = config.GetInt("magic");\n'})
        assert audit_source_drift(src).unregistered == ("magic",)

    def test_known_gated_field_in_active_file_is_flagged(self, tmp_path):
        src = _tree(tmp_path, **{"power__power_module.cpp":
                                 'int w = config.GetInt("channel_width");\n'})
        assert audit_source_drift(src).uncovered_sites == ()
        (src / "routers").mkdir(exist_ok=True)
        (src / "routers" / "iq_router.cpp").write_text(
            'int w = config.GetInt("channel_width");\n')
        report = audit_source_drift(src)
        assert any("channel_width@routers/iq_router.cpp" in s
                   for s in report.uncovered_sites)

    def test_site_without_gates_is_refused(self, tmp_path):
        src = _tree(tmp_path, **{"router.cpp":
                                 'int x = cfg.GetInt("x");\n'})
        sites = {"x": (GatedReadSite("router.cpp", 1, ()),)}
        report = audit_source_drift(src, profile=_EmptyProfile(),
                                    sites=sites)
        assert any("no explicit gate" in s for s in report.uncovered_sites)

    def test_stale_scope_entry_is_flagged(self, tmp_path):
        src = _tree(tmp_path, **{"router.cpp":
                                 'int x = cfg.GetInt("x");\n'})
        report = audit_source_drift(
            src, profile=_EmptyProfile(),
            sites={"other": (GatedReadSite("gone.cpp", 1, (),
                                           ("diagnostic_only",)),)})
        assert report.stale_scope == ("other@gone.cpp",)

    def test_registered_but_removed_read_is_flagged(self, tmp_path):
        src = _tree(tmp_path, **{"router.cpp": 'int x = cfg.GetInt("one");\n'})
        report = audit_source_drift(src)
        assert "num_vcs" in report.stale_registered


class TestGateVerification:
    def test_standalone_rendered_config_satisfies_every_site_gate(
            self, bundle):
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=b"0 0 0 1 1\n")
        verify_gates(_rendered_values(
            prepared.rendered.file("config.cfg").decode()))

    def test_serving_rendered_config_satisfies_every_site_gate(
            self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        verify_gates(_rendered_values(
            prepared.rendered.file("config.cfg").decode()))

    def test_broken_pin_gate_on_a_site_is_detected(self, bundle):
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=b"0 0 0 1 1\n")
        values = _rendered_values(
            prepared.rendered.file("config.cfg").decode())
        values["sim_power"] = "1"
        with pytest.raises(SourceAuditError, match="does not hold"):
            verify_gates(values)

    def test_site_specific_gate_mismatch_is_detected(self, bundle,
                                                     tmp_path):
        # A pin gate attached to the wrong site fails against the rendered
        # config when the pin is not actually held.
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        values = _rendered_values(
            prepared.rendered.file("config.cfg").decode())
        values["router"] = "event"
        with pytest.raises(SourceAuditError,
                           match="const_flits_per_packet@routers/"
                                 "chaos_router.cpp"):
            verify_site_gates(GATED_READ_SITES, values)

    def test_unknown_site_mechanism_is_detected(self):
        sites = {"x": (GatedReadSite("router.cpp", 1, (),
                                     ("not_a_mechanism",)),)}
        with pytest.raises(SourceAuditError, match="unknown gate mechanism"):
            verify_site_gates(sites, {})


class TestEmbeddedMirror:
    """Read-site identity (field, file, count, recovered methods)."""

    def test_mirror_read_sites_match_standalone(self):
        assert MIRROR_SRC.is_dir()

        def fingerprint(root):
            out = {}
            for read in scan_config_reads(root):
                for occ in read.occurrences:
                    key = (read.field, occ.path)
                    out.setdefault(key, []).append(occ.function)
            return {k: sorted(v) for k, v in out.items()}

        assert fingerprint(MIRROR_SRC) == fingerprint(BOOKSIM_SRC)

    def test_every_read_bearing_file_exists_in_mirror(self):
        for read in scan_config_reads(BOOKSIM_SRC):
            for occ in read.occurrences:
                assert (MIRROR_SRC / occ.path).is_file(), occ.path
