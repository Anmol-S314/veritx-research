import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[4] / 'scripts/fix_srota_division_widths.py'
spec = importlib.util.spec_from_file_location('srota_widths', SCRIPT)
widths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(widths)


@pytest.mark.parametrize('operand,kind,bits', [("2'h2", 'CONST', 2), ('capacity', 'VARREF', 16)])
def test_zero_extends_only_diagnosed_unsigned_divisor(operand, kind, bits):
    source = f'  wire [19:0] ratio = numerator / {operand};  // source location\n'
    if kind == 'VARREF':
        source += 'input [15:0] capacity;\n'
    diagnostic = (f"%Warning-WIDTHEXPAND: /tmp/top.v:1:35: Operator DIV expects 20 bits on the RHS, "
                  f"but RHS's {kind} '{operand}' generates {bits} bits.")
    fixed, changes = widths.fix_divisors(source, diagnostic, '/tmp/top.v')
    assert fixed == source.replace(f'/ {operand}', f"/ {{{20 - bits}'b0, {operand}}}")
    assert len(changes) == 1
    assert changes[0]['from_bits'] == bits
    # Zero-extension preserves all unsigned divisor values; it cannot alter
    # division rounding, capacity, or the numerator's bit width.
    for value in range(1, 1 << bits):
        extended = int(f'{value:020b}', 2)
        assert extended == value
        assert ((1 << 20) - 1) // extended == ((1 << 20) - 1) // value


def test_unexpected_structural_warning_is_not_rewritten():
    with pytest.raises(ValueError, match='unreviewed diagnostic'):
        widths.fix_divisors('wire [7:0] x = y / z;\n', '%Warning-LATCH: /tmp/top.v:1:1: bad', '/tmp/top.v')


def test_diagnostic_must_match_operand_and_source():
    diagnostic = ("%Warning-WIDTHEXPAND: /tmp/top.v:1:35: Operator DIV expects 20 bits on the RHS, "
                  "but RHS's VARREF 'capacity' generates 16 bits.")
    with pytest.raises(ValueError, match='does not match'):
        widths.fix_divisors('wire [19:0] ratio = numerator / wrong;\n', diagnostic, '/tmp/top.v')
    with pytest.raises(ValueError, match='unreviewed'):
        widths.fix_divisors('wire [19:0] ratio = numerator / capacity;\n', diagnostic, '/tmp/other.v')
