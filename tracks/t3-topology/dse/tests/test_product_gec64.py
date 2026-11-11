"""64-endpoint product variants use the canonical compiler, not raw fixture labels."""
from pathlib import Path
import sys
import tempfile
import unittest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
from veritx_dse.application.presets import build_versioned_preset_request, preset_catalog
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.core.paths import REPO


class Gec64ProductTest(unittest.TestCase):
    def test_existing_16_endpoint_identity_is_preserved(self):
        expected = {
            'gec_mecs16': '874ca395ebd0a9c7257358434744556b3cc4c782bdc1642b98a357e49b89c43a',
            'gec_hybrid16': '93a408cf65b96d59f852eb8b6a30bc261141c5a6f0cec92b0c6d635a26c86d4b',
        }
        for name, digest in expected.items():
            request, _ = build_versioned_preset_request(name)
            self.assertEqual(request.design_hash(), digest)

    def test_canonical_64_endpoint_presets_are_product_selectable(self):
        ids = {row['preset_id'] for row in preset_catalog()}
        for name in ['gec_mecs64', 'gec_hybrid64']:
            self.assertIn(name, ids)
            request, _ = build_versioned_preset_request(name)
            self.assertEqual(request.topology.concentration, 4)
            self.assertEqual(request.workload.tp, 64)
            self.assertEqual(sum(agent.count for agent in request.agents), 64)

    @unittest.skipUnless((REPO / 'third_party/booksim2/src/booksim').is_file(), 'native BookSim is not built')
    def test_canonical_variants_execute_with_authenticated_evidence(self):
        for name in ['gec_mecs64', 'gec_hybrid64']:
            request, _ = build_versioned_preset_request(name)
            with tempfile.TemporaryDirectory(prefix=name+'-') as directory:
                result = evaluate_product(request, binary=REPO / 'third_party/booksim2/src/booksim',
                                          network_clock_hz=1_000_000_000, timeout_s=45,
                                          run_dir=Path(directory), repo_root=REPO, seed=0)
                self.assertEqual(result.status, 'EVALUATED', result.reason)
                self.assertTrue(result.outcome.evidence_id)
                self.assertTrue(result.outcome.realization_digest)


if __name__ == '__main__':
    unittest.main()
