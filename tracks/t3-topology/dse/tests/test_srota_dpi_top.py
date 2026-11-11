import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / 'scripts/prepare_srota_dpi_top.py'
spec = importlib.util.spec_from_file_location('srota_dpi_top', SCRIPT)
dpi_top = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dpi_top)


def source():
    top = 'module CandidateNoCTop;\n'
    top += ''.join(f'CatalogRouterCell_{i} cell_blackbox_{i} ();\n' for i in range(64))
    return top + 'module CatalogRouterCell_0(input clock); endmodule\n' + ''.join(
        f'module CatalogRouterCell_{i}; endmodule\n' for i in range(1, 64)
    )


def test_map_all_64_real_cells_to_unique_wrappers():
    result = dpi_top.prepare(source())
    assert result.count('srota_cell') == 64
    assert 'CatalogRouterCell_' not in result
    for i in range(64):
        assert f'srota_cell{i} cell_blackbox_{i}' in result


def test_missing_cell_binding_is_rejected():
    with pytest.raises(ValueError, match='expected one instance'):
        dpi_top.prepare(source().replace('CatalogRouterCell_23 cell_blackbox_23 ();\n', ''))
