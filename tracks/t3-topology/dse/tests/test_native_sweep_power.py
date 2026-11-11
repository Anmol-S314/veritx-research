"""Native estimates are scoped tool outputs, never fabricated shared-wire costs."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from native_power import power_evidence, prepare_model  # noqa: E402
import sweep_supported as sweep  # noqa: E402

SUMMARY = '''Overall Traffic Statistics
Packet latency average = 20
Hops average = 3
Accepted packet rate average = 0.009
- Total Power:             2.0
- Total Area:              0.25
'''
MODEL = {'model_id': 'test-model', 'clock_hz': 1e10}


def test_native_summary_and_energy_units():
    result = power_evidence(SUMMARY, 'MESH', 'ok', 0, MODEL)
    assert result['native_model']['status'] == 'AVAILABLE'
    assert result['native_power_w'] == 2
    assert result['native_area_mm2'] == 0.25
    assert result['native_energy_pj_per_cycle'] == pytest.approx(200)


@pytest.mark.parametrize('family', ['GEC_MECS', 'GEC_HYBRID', 'SROTA', 'GEC_EXPRESS', 'UNKNOWN'])
def test_unaudited_families_never_get_native_values(family):
    result = power_evidence(SUMMARY, family, 'ok', 0, MODEL)
    assert result['native_model']['status'] == 'UNSUPPORTED'
    assert result['native_power_w'] is None
    assert result['native_area_mm2'] is None
    assert result['native_energy_pj_per_cycle'] is None


@pytest.mark.parametrize('text,status,rc', [
    ('', 'ok', 0), (SUMMARY, 'unstable', 0), (SUMMARY, 'ok', 1),
    (SUMMARY + SUMMARY, 'ok', 0), (SUMMARY.replace('2.0', 'NaN'), 'ok', 0),
    (SUMMARY.replace('0.25', '-1'), 'ok', 0),
])
def test_failed_or_ambiguous_summaries_are_unavailable(text, status, rc):
    assert power_evidence(text, 'MESH', status, rc, MODEL)['native_model']['status'] == 'UNAVAILABLE'


def test_no_implicit_native_estimate():
    result = power_evidence(SUMMARY, 'MESH', 'ok', 0, None)
    assert result['native_model']['status'] == 'NOT_REQUESTED'
    assert result['native_power_w'] is None


def test_model_inputs_are_snapshotted_and_fingerprinted(tmp_path):
    binary = tmp_path / 'binary'
    binary.write_bytes(b'fake binary for input identity test')
    repo = SCRIPTS.parents[2]
    model = prepare_model(repo, tmp_path / 'run', binary)
    assert model['clock_hz'] == pytest.approx(9712454843.93177)
    assert model['channel_width_bits'] == 128
    assert 'not silicon calibrated' in model['technology']
    assert len(model['tech_sha256']) == len(model['booksim_sha256']) == 64
    assert (tmp_path / 'run/native-model/techfile.txt').read_bytes() == (repo / model['tech_source']).read_bytes()


def test_runner_requests_power_but_rejects_old_shared_wire_output(tmp_path, monkeypatch):
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout=SUMMARY, stderr='', returncode=0)
    monkeypatch.setattr(sweep.subprocess, 'run', run)
    for arm in (sweep.ARMS[0], next(arm for arm in sweep.ARMS if arm.family == 'SROTA')):
        sweep._arm_dir(tmp_path, arm)
        result = sweep._run_one(Path('/fake/booksim'), tmp_path, arm, 0.01, 10, MODEL)
        assert 'sim_power=1' in commands[-1]
        assert result['packet_size_flits'] == 5
        # This fixture has no v2 electrical coverage: finite shared costs are insufficient.
        assert result['native_model']['status'] == ('AVAILABLE' if arm.family == 'MESH' else 'UNSUPPORTED')
        assert (tmp_path / result['log']).is_file()
