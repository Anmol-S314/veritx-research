"""Unit-concentration SROTA keeps its express fabric, not a plain-mesh alias."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.application.presets import build_versioned_preset_request, preset_catalog, _typed_request
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.srota_intent import SrotaIntentError


def request64():
    base, _ = build_versioned_preset_request('srota32')
    intent = replace(base.topology, side_length=8, concentration=1,
                     path_shapes=frozenset({'row', 'column'}), vc_policy='rank')
    return _typed_request(intent, endpoints=64, tp=64)


class Srota64ProductTest(unittest.TestCase):
    def test_concentration_one_retains_express_resources_and_certificate(self):
        request = request64()
        compilation = FabricCompiler().compile(request)
        self.assertEqual(compilation.status, 'COMPILED', compilation.error)
        self.assertEqual(compilation.certificate.overall, 'PASS')
        self.assertEqual(len(compilation.bundle.topology.routers), 64)
        self.assertTrue(compilation.bundle.topology.shared_links)
        self.assertEqual(compilation.bundle.vc_assignment.vc_count, 2)
        self.assertEqual(request.topology.to_dict()['kind'], 'srota')

    def test_plain_nonexpress_unit_mesh_still_uses_mesh_intent(self):
        base, _ = build_versioned_preset_request('srota32')
        with self.assertRaises(SrotaIntentError):
            replace(base.topology, concentration=1, mecs_row=False, mecs_col=False)

    def test_catalog_exposes_the_canonical_variant(self):
        self.assertIn('srota64', {row['preset_id'] for row in preset_catalog()})
        request, _ = build_versioned_preset_request('srota64')
        self.assertEqual(request.design_hash(), request64().design_hash())

    @unittest.skipUnless((REPO / 'third_party/booksim2/src/booksim').is_file(), 'BookSim not built')
    def test_native_execution_authenticates_routes_and_flit_conservation(self):
        with tempfile.TemporaryDirectory(prefix='srota64-canonical-') as directory:
            result = evaluate_product(request64(), binary=REPO/'third_party/booksim2/src/booksim',
                                      network_clock_hz=1_000_000_000, timeout_s=60,
                                      run_dir=Path(directory), repo_root=REPO, seed=0)
            self.assertEqual(result.status, 'EVALUATED', result.reason)
            self.assertTrue(result.outcome.evidence_id)
            self.assertTrue(result.outcome.realization_digest)
            metrics = result.outcome.metrics
            self.assertEqual(metrics['flits_injected'], metrics['flits_accepted'])
            self.assertGreater(metrics['flits_injected'], 0)


if __name__ == '__main__':
    unittest.main()
