"""Source-delivery coverage only; no hardware compilation or qualification."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from veritx_dse.product import chipyard_sources as sources

IDS = {
    'mesh8x8', 'torus8x8', 'cmesh', 'ring', 'gec_mecs', 'fly64', 'qtree',
    'tree4', 'flatfly', 'srota8x8', 'gec_hybrid', 'fattree', 'dragonflynew', 'kncube',
}


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    root = tmp_path / 'candidate-source'
    scala = root / 'src/main/scala'
    for name in ('channel', 'noc', 'router', 'routing', 'topology'):
        (scala / name).mkdir(parents=True)
        (scala / name / 'package.scala').write_text(f'package constellation.{name}\n')
    native = scala / 'constellation/veritx'
    native.mkdir(parents=True)
    for key, entry in sources.EXPORTERS:
        if key != 'kncube':
            (native / f'{entry}.scala').write_text(f'package constellation.veritx\nobject {entry} {{}}\n')
    (root / 'LICENSE').write_text('Fixture license retained verbatim.\n')
    monkeypatch.setenv('VERITX_CHIPYARD_SOURCE_ROOT', str(root))
    return root


def test_all_fourteen_have_distinct_native_entry_points():
    assert {key for key, _ in sources.EXPORTERS} == IDS
    assert len({entry for _, entry in sources.EXPORTERS}) == 14
    dispatcher = (sources.REPO / 'tracks/t3-topology/rtl/chipyard/AllTopologyRtlExport.scala').read_text()
    for key, entry in sources.EXPORTERS:
        assert f'"{key}" -> {entry}.main _' in dispatcher


def test_archive_preserves_all_sources_hashes_and_never_launches_compilers(source_tree, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Source delivery must not execute external commands')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    status = sources.source_inventory()
    assert status['available'] is True
    assert status['target_count'] == 14
    assert all(row['source_present'] for row in status['targets'])
    with zipfile.ZipFile(io.BytesIO(sources.source_archive())) as archive:
        manifest = json.loads(archive.read('source-manifest.json'))
        assert {row['topology_id'] for row in manifest['targets']} == IDS
        assert manifest['final_implementation'] is False
        assert manifest['matches_selected_project'] is False
        assert manifest['generation'] == manifest['simulation'] == 'NOT_RUN'
        assert manifest['qualification'] == 'NOT_QUALIFIED'
        for row in manifest['files']:
            content = archive.read(row['path'])
            assert len(content) == row['bytes']
            assert hashlib.sha256(content).hexdigest() == row['sha256']
        assert archive.read('LICENSE') == (source_tree / 'LICENSE').read_bytes()
        assert b'final case class KNCubeProfile' in archive.read('scala/constellation/veritx/CatalogRtlKNCubeExport.scala')


def test_missing_family_is_not_hidden_as_thirteen_of_fourteen(source_tree):
    (source_tree / 'src/main/scala/constellation/veritx/CatalogRtlHybridExport.scala').unlink()
    assert sources.source_inventory()['available'] is False
    with pytest.raises(sources.ChipyardSourceError, match='gec_hybrid'):
        sources.source_archive()


def test_source_symlink_escape_is_refused(source_tree, tmp_path):
    outside = tmp_path / 'outside.scala'
    outside.write_text('not part of configured source tree')
    (source_tree / 'src/main/scala/escape.scala').symlink_to(outside)
    with pytest.raises(sources.ChipyardSourceError, match='symlink'):
        sources.source_archive()
