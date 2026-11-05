import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gr00t_pipeline',ROOT/'tools/gr00t_pipeline.py')
gp=importlib.util.module_from_spec(spec); spec.loader.exec_module(gp)
LEDGER=ROOT/'data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl'

def test_checked_in_ledger_passes_and_projects_single_observation(tmp_path):
    assert len(gp.read_ledger(LEDGER))==684
    trace=tmp_path/'trace'; manifest=tmp_path/'manifest.json'
    gp.project(LEDGER,trace,manifest)
    assert trace.read_text().splitlines()==['0 0 0 1 62','0 1 0 2 2']
    text=manifest.read_text()
    assert 'NOT model execution traffic' in text and 'single observation at cycle 0' in text

def test_bad_frame_count_fails_closed(tmp_path):
    bad=tmp_path/'bad'; bad.write_text('\n'.join(LEDGER.read_text().splitlines()[:-1])+'\n')
    with pytest.raises(ValueError,match='683 frames'): gp.read_ledger(bad)
