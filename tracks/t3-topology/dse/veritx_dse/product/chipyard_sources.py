"""Source-only delivery for all 14 Chipyard research targets. Never runs a toolchain."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

from veritx_dse.core.paths import REPO

# These are the actual native exporters, not renamed instances of the 2-VC emitter.
EXPORTERS = (
    ('mesh8x8', 'CatalogRtlMeshExport'),
    ('torus8x8', 'CatalogRtlTorusExport'),
    ('cmesh', 'CatalogRtlCmeshExport'),
    ('ring', 'CatalogRtlRingExport'),
    ('gec_mecs', 'CatalogRtlGecMecsExport'),
    ('fly64', 'CatalogRtlFly64Export'),
    ('qtree', 'CatalogRtlQTreeExport'),
    ('tree4', 'CatalogRtlTree4Export'),
    ('flatfly', 'CatalogRtlFlatFlyExport'),
    ('srota8x8', 'CatalogRtlSrotaExport'),
    ('gec_hybrid', 'CatalogRtlHybridExport'),
    ('fattree', 'CatalogRtlFattreeExport'),
    ('dragonflynew', 'CatalogRtlDragonflyExport'),
    ('kncube', 'CatalogRtlKNCubeExport'),
)
_DEFAULT_SOURCE = Path('/home/datavex/.cache/veritx-noc-lab/vla-native-execution/experiments/constellation_topology_rtl/rtl-completion-v3-20261109/execution/build/srota-component-fix-1-corrected/candidate-source')
_MAX_FILES = 512
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024


class ChipyardSourceError(ValueError):
    pass


def _root() -> Path:
    # Only the operator configures source roots; no browser-controlled path.
    return Path(os.environ.get('VERITX_CHIPYARD_SOURCE_ROOT', str(_DEFAULT_SOURCE))).expanduser().resolve()


def _files(repo_root: Path, source_root: Path) -> dict[str, Path]:
    scala = source_root / 'src/main/scala'
    if not all((scala / name).is_dir() for name in ('channel', 'noc', 'router', 'routing', 'topology')):
        raise ChipyardSourceError('The existing Chipyard/Constellation source tree is incomplete or unavailable.')
    files = {}
    for prefix, directory in (('scala', scala),
                              ('resources', source_root / 'src/main/resources'),
                              ('tests', source_root / 'src/test/scala')):
        if directory.is_dir():
            for path in sorted(directory.rglob('*')):
                if path.is_file():
                    resolved = path.resolve()
                    if not resolved.is_relative_to(source_root):
                        raise ChipyardSourceError('A source symlink escapes the configured source tree.')
                    if prefix in ('scala', 'tests') and path.suffix != '.scala':
                        continue
                    files[f'{prefix}/{path.relative_to(directory).as_posix()}'] = resolved
    assets = repo_root / 'tracks/t3-topology/rtl/chipyard'
    for name in ('AllTopologyRtlExport.scala', 'CatalogRtlKNCubeExport.scala'):
        path = assets / name
        if not path.is_file():
            raise ChipyardSourceError(f'Missing source integration: {name}')
        files[f'scala/constellation/veritx/{name}'] = path
    parameterized = assets / 'CompiledFabricPreview.scala'
    if not parameterized.is_file():
        raise ChipyardSourceError('Missing parameterized fabric implementation.')
    # Requires revision-specific SelectedFabric/data; keep it outside the
    # fixed-profile source directory so the native archive remains buildable.
    files['parameterized/CompiledFabricPreview.scala'] = parameterized
    test = assets / 'tests/KNCubeSourceSpec.scala'
    if not test.is_file():
        raise ChipyardSourceError('Missing KNCube source test.')
    files['tests/constellation/veritx/KNCubeSourceSpec.scala'] = test
    for name in ('LICENSE',):
        if not (source_root / name).is_file():
            raise ChipyardSourceError('Constellation source license is missing.')
        files[name] = source_root / name
    files['README.md'] = assets / 'README.md'
    for topology_id, entry in EXPORTERS:
        if f'scala/constellation/veritx/{entry}.scala' not in files:
            raise ChipyardSourceError(f'Missing native exporter source for {topology_id}: {entry}')
    if len(files) > _MAX_FILES:
        raise ChipyardSourceError('Source inventory exceeds the file-count limit.')
    return files


def source_inventory() -> dict:
    try:
        files = _files(REPO, _root())
        reason = None
    except (ChipyardSourceError, OSError) as exc:
        files, reason = {}, str(exc)
    return {
        'scope': 'CHIPYARD_SOURCE_ONLY', 'available': reason is None, 'reason': reason,
        'target_count': len(EXPORTERS), 'source_file_count': len(files),
        'parameterized_core_present': 'parameterized/CompiledFabricPreview.scala' in files,
        'generation': 'NOT_RUN', 'simulation': 'NOT_RUN', 'qualification': 'NOT_QUALIFIED',
        'matches_selected_project': False, 'final_implementation': False,
        'targets': [{'topology_id': key, 'entry_point': f'constellation.veritx.{entry}',
                     'source_present': f'scala/constellation/veritx/{entry}.scala' in files}
                    for key, entry in EXPORTERS],
    }


def source_archive() -> bytes:
    """Snapshot and hash only source bytes; no compilation, lint or simulation."""
    files = _files(REPO, _root())
    output = io.BytesIO()
    inventory, total = [], 0
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, path in sorted(files.items()):
            with path.open('rb') as source:
                data = source.read(_MAX_FILE_BYTES + 1)
            total += len(data)
            if len(data) > _MAX_FILE_BYTES or total > _MAX_TOTAL_BYTES:
                raise ChipyardSourceError('Source snapshot exceeds the byte limit.')
            inventory.append({'path': relative, 'bytes': len(data),
                              'sha256': hashlib.sha256(data).hexdigest()})
            archive.writestr(relative, data)
        manifest = {
            'schema': 'veritx/chipyard-all-topology-sources/1',
            'scope': 'CHIPYARD_SOURCE_ONLY', 'targets': [
                {'topology_id': key, 'entry_point': f'constellation.veritx.{entry}'}
                for key, entry in EXPORTERS],
            'target_count': len(EXPORTERS), 'files': inventory,
            'generation': 'NOT_RUN', 'lint': 'NOT_RUN', 'simulation': 'NOT_RUN',
            'qualification': 'NOT_QUALIFIED', 'matches_selected_project': False,
            'final_implementation': False,
            'limitations': [
                'Existing native exporters retain their pinned research profiles; a family name is not a project-contract match.',
                'The separate parameterized core requires a frozen project contract, recorded route alternatives and matching binary data; it does not infer a graph from a family name.',
                'GEC/SROTA tap-expanded research output is not proof of electrical shared-wire or cycle equivalence.',
                'KNCube implementation is newly written and uncompiled.',
                'SROTA connected tests previously failed; source availability does not supersede that evidence.',
            ],
        }
        archive.writestr('source-manifest.json', json.dumps(manifest, indent=2) + '\n')
    return output.getvalue()
