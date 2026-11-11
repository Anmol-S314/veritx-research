"""Native research names never substitute for different canonical graph identities."""
from pathlib import Path
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.application.presets import build_typed_preset_request, typed_preset_names
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.core.paths import REPO
from veritx_dse.model.topology_artifact import structured_graph


@pytest.mark.parametrize('family,native_routers', [('qtree', 21), ('tree4', 28)])
def test_existing_balanced_tree_is_not_the_native_64_terminal_network(family, native_routers):
    graph = structured_graph(family, {'radix': 4, 'tiers': 3})
    assert graph.nodes == 85
    assert graph.nodes != native_routers
    assert f'{family}64' not in typed_preset_names()


def test_ring_and_multistage_fly_are_not_silently_aliased():
    names = typed_preset_names()
    assert 'ring64' not in names and 'fly64' not in names
    # A flattened butterfly is not a three-stage fly with 48 routers.
    graph = structured_graph('flattened_butterfly', {'radix': 4, 'dimensions': 3})
    assert graph.nodes == 64 != 3 * 4**2
    registry = yaml.safe_load((REPO / 'docs/product/topology-family-registry.yaml').read_text())
    assert registry['families']['ring']['role'] == 'TEST_FIXTURE'
    assert registry['families']['ring']['stages']['AUTHORABLE'] == 'NO'


@pytest.mark.parametrize('name,design_hash', [
    ('qtree7', '2c813e13d552ee3a456340f1ae6a4d4e6e740b6a80c9c52da5dd7b98ef8fffe3'),
    ('tree4_7', 'd5530da7577474c3f3352e23fc489b00642fab5d371f6edf17d258c8a5ea5fc0'),
])
def test_existing_tree_presets_keep_identity_and_execute_exact_graph(name, design_hash):
    request = build_typed_preset_request(name)
    assert request.design_hash() == design_hash
    binary = REPO / 'third_party/booksim2/src/booksim'
    if not binary.is_file():
        pytest.skip('BookSim is not built; canonical identity checked, execution not claimed')
    with tempfile.TemporaryDirectory(prefix='canonical-tree-proof-') as directory:
        result = evaluate_product(request, binary=binary, network_clock_hz=10**9,
            timeout_s=60, run_dir=Path(directory), repo_root=REPO, seed=0)
    assert result.status == 'EVALUATED', result.reason
    assert result.outcome.evidence_id and result.outcome.realization_digest
    assert result.outcome.metrics['flits_injected'] == result.outcome.metrics['flits_accepted'] > 0
