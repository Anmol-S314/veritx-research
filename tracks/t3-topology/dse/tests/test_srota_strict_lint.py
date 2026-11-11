"""The SROTA lint gate must not hide structural diagnostics behind exit zero."""
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / 'scripts/check_srota_hierarchy_lint.py'
spec = importlib.util.spec_from_file_location('strict_srota_lint', SCRIPT)
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


def test_runner_precreated_empty_output_is_accepted(tmp_path):
    output = tmp_path / 'runner-output'
    output.mkdir()
    lint.prepare_output(output)
    (output / 'retained.log').write_text('previous evidence')
    with pytest.raises(FileExistsError):
        lint.prepare_output(output)
    assert (output / 'retained.log').read_text() == 'previous evidence'


def test_structural_warnings_remain_fatal():
    command = lint.lint_command('example', ['example.v'])
    for category in ('fatal', 'WIDTH', 'PINNOTFOUND', 'UNOPTFLAT', 'LATCH', 'UNDRIVEN'):
        assert f'-Wno-{category}' not in command
    assert '-Wall' in command


def test_empty_boundary_waiver_does_not_leak_or_drive_fake_values():
    header = 'module example(input clock, output [7:0] value);'
    stub = lint.boundary_stub(header)
    assert header in stub
    assert stub.startswith('/* verilator lint_off UNDRIVEN */')
    assert stub.endswith('/* verilator lint_on UNDRIVEN */\n')
    assert stub.count('lint_off') == stub.count('lint_on') == 1
    assert 'assign' not in stub
