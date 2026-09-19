"""Wave B3.8i tests — canonical config -> exact rendered bytes -> manifest.

B3.8h proves a BackendConfigArtifact is the canonical lowering of its
bundle. The remaining boundary is the middle chain: a canonical config
can be paired with forged rendered bytes plus a freshly recomputed,
internally valid BackendInputManifest. These tests construct exactly that
attack (recompute every hash, rebuild the manifest) and prove the
canonical-prepared validator and the runner refuse it with zero spawns.
"""
from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, make_capturing_runner, prepare_booksim_standalone,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    CONFIG_FILE, TOPOLOGY_FILE, WORKLOAD_FILE, BookSimLoweringError,
    PreparedBackend, RenderedBackend, assert_canonical_prepared_booksim,
    bind_booksim_inputs, materialize_backend, parse_booksim_config_values,
    run_qualified_booksim, verify_materialized,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendInputError, sha256_bytes,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


@pytest.fixture(scope="module")
def base(bundle):
    return prepare_booksim_standalone(bundle, workload_trace=TRACE)


def _cfg_value(cfg: bytes, key: str, value: str) -> bytes:
    text = cfg.decode()
    new, n = re.subn(rf"^{key} = [^;]*;$", f"{key} = {value};", text, flags=re.M)
    assert n == 1, f"expected exactly one {key!r} line, replaced {n}"
    return new.encode()


def _rebuild(base, files, *, seed=None, manifest=None):
    rendered = RenderedBackend(
        files=tuple(files), sample_period=base.rendered.sample_period,
        trace_summary=base.rendered.trace_summary)
    if manifest is None:
        workload = dict(files)[WORKLOAD_FILE]
        manifest = bind_booksim_inputs(
            base.config, rendered, workload_hash=sha256_bytes(workload),
            seed=seed)
    return PreparedBackend(bundle=base.bundle, config=base.config,
                           rendered=rendered, manifest=manifest)


def _forged_cfg(base, key, value):
    files = [(name, _cfg_value(data, key, value) if name == CONFIG_FILE
              else data) for name, data in base.rendered.files]
    return _rebuild(base, files)


def _never(calls):
    def runner(cmd, cwd, timeout):
        calls["n"] += 1
        raise AssertionError("spawned a noncanonical prepared backend")
    return runner


def _assert_refused(prepared, tmp_path, match=None):
    calls = {"n": 0}
    with pytest.raises(BookSimLoweringError, match=match):
        run_qualified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=_never(calls), binary=tmp_path / "fake")
    assert calls["n"] == 0, "process spawned despite refusal"
    assert not (tmp_path / "backend").exists(), \
        "noncanonical prepared backend was materialized before refusal"


def _run_ok(prepared, tmp_path):
    return run_qualified_booksim(
        prepared, run_dir=tmp_path, repo_root=tmp_path,
        runner=make_capturing_runner(prepared.bundle, prepared.config),
        binary=tmp_path / "fake")


class TestCanonicalBaseline:
    def test_prepare_passes_and_runs(self, base, tmp_path):
        assert_canonical_prepared_booksim(base)
        ev = _run_ok(base, tmp_path)
        assert ev.route_equivalence == "EXACT"
        assert ev.seed_policy == "pinned_default"

    def test_parser_rejects_duplicate_keys(self):
        with pytest.raises(BookSimLoweringError, match="duplicate"):
            parse_booksim_config_values("a = 1;\nb = 2;\na = 3;\n")

    def test_parser_rejects_malformed_lines(self):
        with pytest.raises(BookSimLoweringError, match="malformed"):
            parse_booksim_config_values("a = 1;\nthis is not a config\n")

    def test_parser_skips_comments_only(self):
        got = parse_booksim_config_values(
            "// comment\n# other\nnetwork_file = topology.anynet;\n")
        assert got == {"network_file": "topology.anynet"}


class TestForgedRenderedConfig:
    @pytest.mark.parametrize("field,value", [
        ("num_vcs", "99"),
        ("vc_buf_size", "64"),
        ("routing_delay", "7"),
        ("credit_delay", "9"),
        ("input_speedup", "4"),
        ("output_speedup", "3"),
        ("vc_allocator", "pim"),
        ("sw_allocator", "pim"),
        ("alloc_iters", "5"),
        ("speculative", "1"),
        ("noq", "1"),
    ])
    def test_canonical_config_forged_active_field(self, base, tmp_path,
                                                  field, value):
        forged = _forged_cfg(base, field, value)
        # The attack is coherent: the manifest binds the forged bytes.
        assert forged.manifest.input(CONFIG_FILE).sha256 == \
            sha256_bytes(dict(forged.rendered.files)[CONFIG_FILE])
        with pytest.raises(BookSimLoweringError, match="byte mismatch"):
            assert_canonical_prepared_booksim(forged)
        _assert_refused(forged, tmp_path)

    @pytest.mark.parametrize("field,value", [
        ("sample_period", "123456"),
        ("traffic", "uniform"),
        ("routing_dump_file", "other.dump"),
    ])
    def test_workload_derived_config_forgery(self, base, tmp_path, field,
                                             value):
        forged = _forged_cfg(base, field, value)
        with pytest.raises(BookSimLoweringError, match="byte mismatch"):
            assert_canonical_prepared_booksim(forged)
        _assert_refused(forged, tmp_path)


class TestSeedSemantics:
    def test_config_and_manifest_seed_disagree(self, base, tmp_path):
        # config.cfg seed=42, manifest claims seed=7 (recomputed, valid).
        forged = _forged_cfg(base, "seed", "42")
        manifest = replace(forged.manifest, seed=7,
                           seed_policy="explicit", artifact_hash="")
        prepared = _rebuild(base, forged.rendered.files, manifest=manifest)
        with pytest.raises(BookSimLoweringError, match="byte mismatch"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_pinned_default_with_nondefault_seed(self, bundle, tmp_path):
        explicit = prepare_booksim_standalone(
            bundle, workload_trace=TRACE, seed=7)
        forged = replace(explicit.manifest, seed_policy="pinned_default",
                         artifact_hash="")
        prepared = replace(explicit, manifest=forged)
        with pytest.raises(BookSimLoweringError,
                           match="pinned_default requires"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_garbage_seed_policy(self, base, tmp_path):
        forged = replace(base.manifest, seed_policy="garbage",
                         artifact_hash="")
        prepared = replace(base, manifest=forged)
        with pytest.raises(BookSimLoweringError,
                           match="unsupported seed_policy"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_canonical_default_seed_passes(self, base, tmp_path):
        assert _run_ok(base, tmp_path).seed_policy == "pinned_default"

    def test_canonical_explicit_seed_passes(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=TRACE, seed=7)
        assert_canonical_prepared_booksim(prepared)
        ev = _run_ok(prepared, tmp_path)
        assert ev.seed == 7 and ev.seed_policy == "explicit"


class TestManifestForgery:
    def _prepared(self, base, **changes):
        manifest = replace(base.manifest, artifact_hash="", **changes)
        return replace(base, manifest=manifest)

    def test_false_workload_hash(self, base, tmp_path):
        prepared = self._prepared(
            base, workload_hash=sha256_bytes(b"unrelated workload"))
        # The rendered workload input hash is still truthful...
        assert prepared.manifest.input(WORKLOAD_FILE).sha256 == \
            sha256_bytes(dict(prepared.rendered.files)[WORKLOAD_FILE])
        with pytest.raises(BookSimLoweringError, match="differs in"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_false_execution_mode(self, base, tmp_path):
        prepared = self._prepared(base, execution_mode="FAKE")
        with pytest.raises(BookSimLoweringError, match="differs in"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_false_invocation_args(self, base, tmp_path):
        prepared = self._prepared(
            base, invocation_args=(("config-file", "other.cfg"),))
        with pytest.raises(BookSimLoweringError, match="differs in"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_false_input_role(self, base, tmp_path):
        inputs = tuple(
            replace(r, role="workload")
            if r.logical_name == CONFIG_FILE else r
            for r in base.manifest.rendered_inputs)
        prepared = self._prepared(base, rendered_inputs=inputs)
        with pytest.raises(BookSimLoweringError, match="differs in"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)


class TestFileSetAttacks:
    def test_extra_file_with_canonical_manifest(self, base, tmp_path):
        files = list(base.rendered.files) + [("extra.input", b"extra")]
        prepared = _rebuild(base, files, manifest=base.manifest)
        with pytest.raises(BookSimLoweringError, match="file set"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_extra_file_cannot_be_manifest_bound(self, base):
        files = list(base.rendered.files) + [("extra.input", b"extra")]
        rendered = RenderedBackend(
            files=tuple(files), sample_period=base.rendered.sample_period,
            trace_summary=base.rendered.trace_summary)
        with pytest.raises(BackendInputError, match="role"):
            bind_booksim_inputs(
                base.config, rendered,
                workload_hash=sha256_bytes(dict(files)[WORKLOAD_FILE]))

    def test_missing_config_file(self, base, tmp_path):
        files = [f for f in base.rendered.files if f[0] != CONFIG_FILE]
        prepared = _rebuild(base, files, manifest=base.manifest)
        with pytest.raises(BookSimLoweringError, match="file set"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_missing_workload_file(self, base, tmp_path):
        files = [f for f in base.rendered.files if f[0] != WORKLOAD_FILE]
        prepared = _rebuild(base, files, manifest=base.manifest)
        with pytest.raises(BookSimLoweringError, match="workload"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_missing_topology_file(self, base, tmp_path):
        files = [f for f in base.rendered.files if f[0] != TOPOLOGY_FILE]
        prepared = _rebuild(base, files, manifest=base.manifest)
        with pytest.raises(BookSimLoweringError, match="file set"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)

    def test_duplicate_logical_file(self, base, tmp_path):
        cfg = dict(base.rendered.files)[CONFIG_FILE]
        files = list(base.rendered.files) + [(CONFIG_FILE, cfg)]
        prepared = _rebuild(base, files, manifest=base.manifest)
        with pytest.raises(BookSimLoweringError, match="duplicate"):
            assert_canonical_prepared_booksim(prepared)
        _assert_refused(prepared, tmp_path)


class TestWorkloadMutation:
    def test_changed_workload_is_accepted_with_new_hash(self, bundle,
                                                        tmp_path):
        changed = TRACE + b"20 1 3 0 1\n"
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=changed)
        assert_canonical_prepared_booksim(prepared)
        baseline = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        assert prepared.manifest.backend_input_hash() != \
            baseline.manifest.backend_input_hash()
        assert prepared.manifest.workload_hash == sha256_bytes(changed)
        ev = _run_ok(prepared, tmp_path)
        assert ev.workload_hash == sha256_bytes(changed)


class TestMaterializedTamperStillIndependent:
    def test_disk_tamper_after_materialization(self, base, tmp_path):
        materialize_backend(base.rendered, base.manifest, tmp_path)
        (tmp_path / CONFIG_FILE).write_bytes(
            _cfg_value(base.rendered.file(CONFIG_FILE), "num_vcs", "99"))
        with pytest.raises(Exception, match="modified after planning"):
            verify_materialized(base.manifest, tmp_path)
