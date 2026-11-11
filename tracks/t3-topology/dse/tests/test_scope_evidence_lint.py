from pathlib import Path

import pytest

from veritx_dse.product.scope_evidence import row_from_lint_sim


def _row(tmp_path, lint="", sim="status: PASS\n", scenarios=None):
    lint_log, sim_log = tmp_path / "lint.log", tmp_path / "sim.log"
    lint_log.write_text(lint)
    sim_log.write_text(sim)
    return row_from_lint_sim(lint_status="PASS", sim_status="PASS",
                             scenarios={"drain": True} if scenarios is None else scenarios,
                             lint_log=lint_log, sim_log=sim_log)


def test_clean_lint_and_actual_sim_log_close_row(tmp_path):
    row = _row(tmp_path)
    assert row["status"] == "CLOSED"
    assert all(row["sha256"].values())


@pytest.mark.parametrize("warning", ["UNUSEDSIGNAL", "UNDRIVEN", "WIDTH", "LATCH"])
def test_exit_zero_with_warnings_never_means_clean(tmp_path, warning):
    row = _row(tmp_path, lint=f"%Warning-{warning}: something\n")
    assert row["status"] == "OPEN"
    assert row["measured"]["lint_warnings"] == 1


@pytest.mark.parametrize("scenarios", [{}, {"drain": False}, {"drain": 1}])
def test_empty_or_non_boolean_scenarios_cannot_close_row(tmp_path, scenarios):
    assert _row(tmp_path, scenarios=scenarios)["status"] == "OPEN"


@pytest.mark.parametrize("sim", ["", "status: FAIL\n", "status: PASS\nstatus: FAIL\n"])
def test_absent_or_conflicting_simulation_success_cannot_close_row(tmp_path, sim):
    assert _row(tmp_path, sim=sim)["status"] == "OPEN"


def test_missing_logs_cannot_close_row(tmp_path):
    row = row_from_lint_sim(lint_status="PASS", sim_status="PASS",
                           scenarios={"drain": True},
                           lint_log=tmp_path / "absent", sim_log=tmp_path / "absent-sim")
    assert row["status"] == "OPEN"
