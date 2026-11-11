"""Public research CLI contracts; no dataset download needed for unit tests."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gr00t_pipeline', ROOT / 'tools/gr00t_pipeline.py')
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)
LEDGER = ROOT / 'data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl'


def test_pinned_ledger_and_all_three_payloads_conserve_flits(tmp_path):
    assert len(gp.read_ledger(LEDGER)) == 684
    trace, manifest = tmp_path / 'trace', tmp_path / 'manifest.json'
    result = gp.project(LEDGER, trace, manifest)
    # Source episode-0 frame: H264 15,638 B + state 344 B + action 344 B.
    assert result['payload_bytes'] == 16326
    assert result['flits'] == 511  # ceil(15638/32) + 11 + 11
    assert result['padded_bytes'] == 16352
    assert {t['kind']: t['payload_bytes'] for t in result['transfers']} == {
        'camera_h264': 15638, 'state': 344, 'action_demonstration': 344}
    packets = [tuple(map(int, line.split())) for line in trace.read_text().splitlines()]
    assert len(packets) == 33 and sum(row[-1] for row in packets) == 511
    assert all(1 <= row[-1] <= 16 for row in packets)
    assert packets == sorted(packets)
    assert 'NOT model execution traffic' in result['label']
    assert json.loads(manifest.read_text()) == result


def test_projection_reads_sizes_from_selected_source_frames(tmp_path):
    result = gp.project(LEDGER, tmp_path / 'trace', tmp_path / 'manifest', frames=2,
                        max_cycles=21000000)
    frames = gp.read_ledger(LEDGER)
    camera = [t for t in result['transfers'] if t['kind'] == 'camera_h264']
    assert [t['payload_bytes'] for t in camera] == [
        frames[1]['h264_demux_packet_bytes'], frames[2]['h264_demux_packet_bytes']]
    assert camera[1]['release_cycle'] == 20000000


def test_packet_requests_respect_authored_one_flit_per_source_cycle(tmp_path):
    gp.project(LEDGER, tmp_path / 'trace', tmp_path / 'manifest')
    packets = [tuple(map(int, line.split())) for line in (tmp_path / 'trace').read_text().splitlines()]
    previous = {}
    for cycle, src, _, _, size in packets:
        assert cycle >= previous.get(src, 0)
        previous[src] = cycle + size


@pytest.mark.parametrize('mutation', ['truncate', 'payload', 'nan_pts', 'source'])
def test_tampered_ledger_cannot_reuse_claimed_source_hashes(tmp_path, mutation):
    text = LEDGER.read_text()
    if mutation == 'truncate':
        text = '\n'.join(text.splitlines()[:-1]) + '\n'
    elif mutation == 'payload':
        text = text.replace('"h264_demux_packet_bytes":15638', '"h264_demux_packet_bytes":1', 1)
    elif mutation == 'nan_pts':
        text = text.replace('"video_pts_s":0.0', '"video_pts_s":NaN', 1)
    else:
        text = text.replace(gp.REVISION, '0' * 40, 1)
    bad = tmp_path / 'bad.jsonl'
    bad.write_text(text)
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        gp.read_ledger(bad)


def test_project_refuses_same_path_existing_files_and_long_idle_timeline(tmp_path):
    existing = tmp_path / 'existing'
    existing.write_text('preserve')
    with pytest.raises(ValueError, match='distinct new'):
        gp.project(LEDGER, existing, tmp_path / 'manifest')
    assert existing.read_text() == 'preserve'
    with pytest.raises(ValueError, match='distinct new'):
        gp.project(LEDGER, tmp_path / 'same', tmp_path / 'same')
    with pytest.raises(ValueError, match='max-cycles'):
        gp.project(LEDGER, tmp_path / 'trace', tmp_path / 'manifest', frames=2)
    assert not (tmp_path / 'trace').exists()


@pytest.mark.parametrize('kwargs', [{'frames': 0}, {'frames': 684}, {'flit_bytes': 0},
                                    {'max_packet_flits': -1}, {'clock_hz': True}])
def test_invalid_projection_parameters_refuse(tmp_path, kwargs):
    with pytest.raises(ValueError):
        gp.project(LEDGER, tmp_path / 'trace', tmp_path / 'manifest', **kwargs)


def test_fetch_uses_exact_nested_paths_and_checks_hashes(tmp_path, monkeypatch):
    urls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            return b'incorrect source'
    def urlopen(request, timeout):
        urls.append((request.full_url, timeout))
        return Response()
    monkeypatch.setattr(gp.urllib.request, 'urlopen', urlopen)
    with pytest.raises(ValueError, match='size/hash mismatch'):
        gp.fetch(tmp_path / 'sample')
    assert urls == [(f'https://huggingface.co/datasets/{gp.REPO}/resolve/{gp.REVISION}/'
                     f'{gp.SUBSET}/data/chunk-000/episode_000000.parquet', 30)]
    assert not (tmp_path / 'sample/episode_000000.parquet').exists()


def test_export_rejects_wrong_raw_source_before_reading_optional_dependencies(tmp_path):
    wrong = tmp_path / 'bad.parquet'
    wrong.write_bytes(b'bad')
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        gp.export_ledger(wrong, tmp_path / 'absent.mp4', tmp_path / 'output')


def test_retired_packet_log_conserves_exact_source_requests(tmp_path):
    trace = tmp_path / 'trace'
    trace.write_text('0 0 0 1 16\n16 0 0 1 2\n')
    log = tmp_path / 'packets.csv'
    log.write_text('packet_id,src,dst,packet_size_flits,request_time,injection_time,arrival_time\n'
                   '1,0,1,2,16,20,30\n0,0,1,16,0,15,43\n')
    result = gp.check_packet_log(log, trace)
    assert result['packets'] == 2 and result['flits'] == 18
    assert result['request_latency_avg'] == 28.5
    assert result['request_latency_p99'] == 43
    log.write_text(log.read_text().replace('1,0,1,2,16,20,30', '1,0,1,2,15,20,30'))
    with pytest.raises(ValueError, match='conserve exact'):
        gp.check_packet_log(log, trace)


def test_real_booksim_smoke_binds_native_trace_manager_and_exact_packets(tmp_path):
    binary = gp.ROOT / 'third_party/booksim2/src/booksim'
    if not binary.is_file():
        pytest.skip('optional native BookSim binary unavailable')
    result = gp.run_booksim_smoke(LEDGER, tmp_path / 'run', timeout=20)
    config = (tmp_path / 'run/booksim.cfg').read_text()
    assert 'sim_type = trace;' in config
    assert f'trace_file = {tmp_path / "run/workload.trace"};' in config
    assert result['exit_status'] == 0 and result['exact_fabric_eligible'] is False
    assert result['observed_packet_metrics_cycles']['packets'] == 33
    assert result['observed_packet_metrics_cycles']['flits'] == 511
    assert result['observed_packet_metrics_cycles']['last_arrival_cycle'] > 0


def test_precision_requires_all_resolved_timeloop_levels_not_yaml():
    f32 = ('Word bits : 32\nData word bits : 32\n'
           'Data word bits : 32\nData word bits : 32\n')
    assert gp.require_timeloop_precision(f32, 32) == [32, 32, 32, 32]
    networks = '\nNetworks\n--------\n' + 'Network\nWord bits : 32\n' * 3
    assert gp.require_timeloop_precision(f32 + networks, 32) == [32, 32, 32, 32]
    for stale in (f32.replace('32', '8'), f32.replace('bits : 32', 'bits : 8', 1),
                  'word-bits: 32\n' * 4, f32.splitlines()[0]):
        with pytest.raises(ValueError, match='resolved word widths'):
            gp.require_timeloop_precision(stale, 32)


def test_timeloop_missing_binary_has_no_fake_result(tmp_path):
    with pytest.raises(RuntimeError, match='unavailable'):
        gp.timeloop_smoke(tmp_path / 'run', tmp_path / 'missing')
    assert not (tmp_path / 'run').exists()
