from pathlib import Path


def package_text():
    pkg=Path(__file__).parents[1]/"src"/"veritx_dse"
    return "\n".join(p.read_text() for p in pkg.rglob("*.py"))


def test_no_wave_named_live_packages():
    pkg=Path(__file__).parents[1]/"src"/"veritx_dse"
    assert not (pkg/"waved").exists()
    assert not (pkg/"wavee").exists()


def test_no_wave_class_names_in_live_source():
    text=package_text()
    assert "WaveD" not in text
    assert "WaveE" not in text
