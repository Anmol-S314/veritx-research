"""Wave B3.8d tests — golden fabric corpus.

Five deterministic fabrics with pinned artifact/route/loss hashes and a
real BookSim execution per case. Any semantic change to the lowering,
projection or route authority shows up as a diff here, and the executed
route dump must match the pinned expectation.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import TRACE, rebuild_bundle  # noqa: E402
from test_backend_bundle import make_bundle  # noqa: E402
from test_backend_execution_qualification import _vc  # noqa: E402
from test_fabric_artifact import _with_hbm, build_chain  # noqa: E402

from veritx_dse.backend.analytical import (  # noqa: E402
    lower_analytical_aware, lower_analytical_unaware,
)
from veritx_dse.backend.booksim import (  # noqa: E402
    bind_booksim_inputs, expected_route_table, lower_booksim_standalone,
    prepare_booksim_standalone, render_booksim_standalone,
    run_certified_booksim,
)
from veritx_dse.backend.contracts import sha256_bytes  # noqa: E402
from veritx_dse.backend.serving import lower_serving_booksim  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.core.spec import canonical_json  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "backend_golden.json"
CHAIN = build_chain()


def _cases():
    chain = CHAIN
    return {
        "mesh4_multiclass": make_bundle(chain),
        "mesh4_singleclass": rebuild_bundle(
            chain, vc=_vc(chain, classes={"DEFAULT": [0, 1]})),
        "hbm5_addrmap": make_bundle(_with_hbm()),
        "wide128": make_bundle(build_chain(link_width=128)),
        "escape_blocked": rebuild_bundle(chain, vc=_vc(chain, escape=(0,))),
    }


@pytest.fixture(scope="module")
def corpus():
    return json.loads(CORPUS_PATH.read_text())


@pytest.fixture(scope="module")
def cases():
    return _cases()


def _loss_digest(art):
    return hashlib.sha256(
        canonical_json(list(art.semantic_loss_summary())).encode()
    ).hexdigest()


def _route_digest(bundle, art):
    table = expected_route_table(bundle, art)
    rows = [[r, e, table[(r, e)]] for r, e in sorted(table)]
    return hashlib.sha256(canonical_json(rows).encode()).hexdigest()


def _observed(bundle):
    n = bundle.attachment.endpoint_count
    trace = f"0 0 0 {n - 1} 2\n10 {n - 1} 0 0 2\n".encode()
    art = lower_booksim_standalone(bundle)
    rendered = render_booksim_standalone(bundle, art, workload_trace=trace)
    manifest = bind_booksim_inputs(
        art, rendered, workload_hash=sha256_bytes(trace))
    return trace, {
        "endpoint_count": n,
        "fabric_hash": bundle.fabric.fabric_hash(),
        "standalone_config_hash": art.backend_config_hash(),
        "standalone_input_hash": manifest.backend_input_hash(),
        "route_expected_sha256": _route_digest(bundle, art),
        "exact_fabric_eligible": art.exact_fabric_eligible(),
        "loss_digest": _loss_digest(art),
        "serving_config_hash": lower_serving_booksim(bundle)
        .backend_config_hash(),
        "flit_bytes": bundle.packet_format.flit_width_bits // 8,
        "aware_config_hash": lower_analytical_aware(
            bundle, network_dims=(n,)).config.backend_config_hash(),
        "unaware_config_hash": lower_analytical_unaware(
            bundle, network_dims=(n,)).config.backend_config_hash(),
    }


class TestGoldenHashes:
    def test_corpus_shape(self, corpus):
        assert corpus["schema"] == 1
        assert corpus["profile"] == "CERTIFIED_BOOKSIM_ANYNET_V1"
        assert set(corpus["cases"]) == set(_cases())

    def test_every_case_matches_pinned_hashes(self, corpus, cases):
        for name, bundle in cases.items():
            expected = corpus["cases"][name]
            trace, observed = _observed(bundle)
            assert trace.decode() == expected["trace"], name
            for key, value in observed.items():
                assert value == expected[key], (
                    f"{name}: {key} changed\n"
                    f"  pinned:   {expected[key]!r}\n"
                    f"  observed: {value!r}")

    def test_corpus_covers_exact_and_blocked_domains(self, corpus):
        eligible = [n for n, row in corpus["cases"].items()
                    if row["exact_fabric_eligible"]]
        assert eligible == []
        losses = {n: row["loss_digest"] for n, row in corpus["cases"].items()}
        # Distinct fabrics mostly share loss shapes; single-class removes
        # the VC-class coarsening, so its loss digest must differ.
        assert losses["mesh4_singleclass"] != losses["mesh4_multiclass"]


class TestGoldenExecution:
    def test_real_execution_matches_every_pinned_case(
            self, corpus, cases, tmp_path):
        from veritx_dse.simulation.booksim import find_booksim_bin
        try:
            binary = find_booksim_bin(REPO)
        except FileNotFoundError:
            pytest.skip("no runnable BookSim binary")
        for name, bundle in cases.items():
            expected = corpus["cases"][name]
            prepared = prepare_booksim_standalone(
                bundle, workload_trace=expected["trace"].encode())
            assert prepared.config.backend_config_hash() \
                == expected["standalone_config_hash"], name
            assert prepared.manifest.backend_input_hash() \
                == expected["standalone_input_hash"], name
            ev = run_certified_booksim(
                prepared, run_dir=tmp_path / name,
                repo_root=REPO, timeout=120, binary=Path(binary))
            assert ev.route_equivalence == "EXACT", name
            assert ev.route_expected_sha256 == \
                expected["route_expected_sha256"], name
            assert ev.route_executed_sha256 == \
                expected["route_expected_sha256"], name
            assert ev.stats.get("delivered") == 2, name
