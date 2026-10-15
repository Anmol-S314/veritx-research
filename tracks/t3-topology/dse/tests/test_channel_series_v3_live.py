"""Live v3 series (simulation-overlay Phase C): real-binary conservation.

Mirrors the T6 end-to-end test (test_channel_measurements.py): the REAL
fork binary runs an in-repo config with the series keys, and the typed
v3 reader must conserve exactly — window sums equal the independent
cumulative dump, and single-window and multi-window runs of the same
config agree on every telescoping total. The max>=mean invariant holds
per window per channel by fork construction.

NOTE on override values: the fork's argv grammar only accepts string
values that lead with alpha (a pre-existing yacc limitation), so hashes
are alpha-prefixed here. File-based configs (production path) are
unaffected.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

cs = pytest.importorskip("veritx_dse.backend.channel_series")
from veritx_dse.core.paths import BOOKSIM_BIN  # noqa: E402

CONFIG = REPO / "tracks/t3-topology/configs/cmesh16.cfg"

TELESCOPING_KEYS = (
    "flits_per_window",
    "queue_cycles_per_window",
    "arb_wait_cycles_per_window",
    "tx_flits_per_window",
    "tx_busy_cycles_per_window",
    "occupancy_flit_cycles_per_window",
)


def _run(tmp_path: Path, period: int, run_hash: str,
         extra: tuple[str, ...] = ()) -> Path:
    out = tmp_path / run_hash
    out.mkdir()
    cmd = [str(BOOKSIM_BIN), str(CONFIG),
           "channel_timeseries_output=channel_timeseries.json",
           f"sample_period_cycles={period}",
           f"run_hash={run_hash}",
           "run_binary_hash=h0123456789abcdef",
           "link_capacity_flits_per_cycle=1",
           "channel_activity_output=activity.json",
           *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          cwd=str(out))
    assert proc.returncode == 0, proc.stderr[-2000:]
    return out


def _emitted_flits(run_dir: Path) -> int:
    doc = json.loads((run_dir / "activity.json").read_text())
    return sum(sum(o["flits_by_class"])
               for r in doc["routers"] for o in r["output_activity"])


def _totals(artifact) -> dict:
    return {k: sum(sum(getattr(c, k)) for c in artifact.channels)
            for k in TELESCOPING_KEYS}


def _check_shape(artifact) -> None:
    assert artifact.schema_version == 3
    assert artifact.num_windows > 0
    ref = None
    for channel in artifact.channels:
        assert len(channel.flits_per_window) == artifact.num_windows
        assert len(channel.window_cycles) == artifact.num_windows
        assert all(s > 0 for s in channel.window_cycles)
        for key in TELESCOPING_KEYS:
            assert len(getattr(channel, key)) == artifact.num_windows
        assert channel.stalls_per_window is None
        assert channel.has_split()
        if ref is None:
            ref = channel.window_cycles
        assert channel.window_cycles == ref


def test_live_v3_single_and_multi_window_telescope(tmp_path):
    """Real binary, real counters: windows sum to the cumulative dump,
    and the sampling period changes nothing about the totals."""
    if not Path(BOOKSIM_BIN).is_file():
        pytest.skip("booksim binary absent")
    single = _run(tmp_path, 1000000000, "phaseCsingle")
    multi = _run(tmp_path, 100, "phaseCmulti")
    art_single = cs.load_series(str(single / "channel_timeseries.json"))
    art_multi = cs.load_series(str(multi / "channel_timeseries.json"))
    _check_shape(art_single)
    _check_shape(art_multi)
    assert (_totals(art_single)["flits_per_window"]
            == _emitted_flits(single) > 0)
    assert (_totals(art_multi)["flits_per_window"]
            == _emitted_flits(multi) > 0)
    assert _totals(art_single) == _totals(art_multi)
    grants = _totals(art_multi)["tx_flits_per_window"]
    flits = _totals(art_multi)["flits_per_window"]
    assert grants >= flits  # difference is crossbar in-flight at dump
    latency = (( _totals(art_multi)["queue_cycles_per_window"]
                + _totals(art_multi)["arb_wait_cycles_per_window"]) / grants)
    assert latency > 0


def test_live_v3_max_geq_mean_per_window(tmp_path):
    """Maxima share their means' denominator by fork construction."""
    if not Path(BOOKSIM_BIN).is_file():
        pytest.skip("booksim binary absent")
    run = _run(tmp_path, 100, "phaseCmaxmean")
    artifact = cs.load_series(str(run / "channel_timeseries.json"))
    _check_shape(artifact)
    for channel in artifact.channels:
        for window, span in enumerate(channel.window_cycles):
            assert (channel.occupancy_max_per_window[window] * span
                    >= channel.occupancy_flit_cycles_per_window[window])
            grants = channel.tx_flits_per_window[window]
            if grants > 0:
                assert (channel.queue_max_per_window[window] * grants
                        >= channel.queue_cycles_per_window[window])
                assert (channel.arb_max_per_window[window] * grants
                        >= channel.arb_wait_cycles_per_window[window])


def test_live_v3_multi_epoch_conserves(tmp_path):
    """Five sims: wall-time resets re-baseline, conservation telescopes."""
    if not Path(BOOKSIM_BIN).is_file():
        pytest.skip("booksim binary absent")
    run = _run(tmp_path, 100, "phaseCepochs", extra=("sim_count=5",))
    artifact = cs.load_series(str(run / "channel_timeseries.json"))
    _check_shape(artifact)
    assert artifact.time_resets_observed == 4
    assert (_totals(artifact)["flits_per_window"]
            == _emitted_flits(run) > 0)


def test_live_v3_disabled_run_emits_nothing(tmp_path):
    """Key absent: the binary must not write anything extra."""
    if not Path(BOOKSIM_BIN).is_file():
        pytest.skip("booksim binary absent")
    out = tmp_path / "phaseCdisabled"
    out.mkdir()
    proc = subprocess.run([str(BOOKSIM_BIN), str(CONFIG)],
                          capture_output=True, text=True, timeout=300,
                          cwd=str(out))
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert list(out.glob("*.json")) == []
