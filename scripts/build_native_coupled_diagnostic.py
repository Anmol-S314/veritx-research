#!/usr/bin/env python3
"""Build diagnostic engines from isolated vendor copies; never re-pin producers.

Usage: python scripts/build_native_coupled_diagnostic.py /absolute/new/cache/dir
Requires the vendored dependency sources already present, CMake, C++, flex/bison,
and this Python's development headers. No dependency installation/downloads.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def pin(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return {'path': str(path.resolve()), 'sha256': h.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--booksim-only', action='store_true',
                        help='build only the BookSim producer required for native multicast')
    args = parser.parse_args()
    out = args.output.expanduser().resolve()
    if out.is_relative_to(REPO) or out.is_relative_to(Path('/tmp')):
        parser.error('use a new disk-backed directory outside the repository and /tmp')
    out.mkdir(parents=True, exist_ok=False)
    commands = []
    def run(command, cwd, log):
        commands.append({'argv': list(map(str, command)), 'cwd': str(cwd), 'log': str(log)})
        with log.open('wb') as stream:
            subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=1200, check=True)
    ignore = shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache', 'build',
        '*.o', '*.d', '*.a', '*.so', '*.so.*', 'booksim', 'routing.dump')
    booksim = out / 'booksim2'
    ramulator = out / 'ramulator2'
    # Only the vendor trees, not a copy/worktree of the full repository.
    shutil.copytree(REPO / 'third_party/booksim2', booksim, ignore=ignore)
    if not args.booksim_only:
        shutil.copytree(REPO / 'third_party/ramulator2', ramulator, ignore=ignore)
    source = booksim / 'src'
    compiler = Path(shutil.which('c++')).resolve()
    make_tool = Path(shutil.which('make')).resolve()
    driver = out / 'native_booksim_driver.cpp'
    shutil.copy2(REPO / 'tracks/t3-topology/dse/backend/native_booksim_driver.cpp', driver)
    run([make_tool, '-j1', 'lib'], source, out / 'booksim-build.log')
    binary = out / 'native_booksim_driver'
    includes = [source] + [source / sub for sub in ('routers', 'networks', 'arbiters', 'allocators', 'power')]
    run([compiler, '-O2', *['-I' + str(p) for p in includes], driver,
         source / 'veritx_embed.cpp', source / 'libveritx_embed.a', '-o', binary], out, out / 'booksim-driver-build.log')
    if args.booksim_only:
        extensions = []
    else:
        build = out / 'ramulator-build'
        run(['cmake', '-S', ramulator, '-B', build, '-DPython_EXECUTABLE=' + sys.executable,
             '-DRAMULATOR_PYTHON_BINDINGS=ON', '-DFETCHCONTENT_FULLY_DISCONNECTED=ON'], out, out / 'ramulator-configure.log')
        run(['cmake', '--build', build, '--target', '_ramulator', '-j1'], out, out / 'ramulator-build.log')
        extensions = list((ramulator / 'python/ramulator').glob('_ramulator.*.so'))
        if len(extensions) != 1:
            raise RuntimeError('expected one extension for the current Python ABI')
    source_manifests = {}
    source_roots = [('booksim', booksim)]
    if not args.booksim_only:
        source_roots.append(('ramulator', ramulator))
    for name, root in source_roots:
        files = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink()
                 and p.suffix in ('.cpp', '.hpp', '.h', '.c', '.l', '.y', '.py', '.cmake', '.txt')
                 and '__pycache__' not in p.parts]
        files.extend(p for p in root.rglob('Makefile') if p.is_file())
        if name == 'booksim': files.append(driver)
        path = out / (name + '-sources.json')
        path.write_text(json.dumps({'files': [pin(p) for p in sorted(set(files))]}, indent=2) + '\n')
        source_manifests[name] = path
    booksim_commands = [
        {'argv': [str(make_tool), '-j1', 'lib']},
        {'argv': [str(compiler), '-O2', *['-I' + str(p) for p in includes],
                  str(driver), str(source / 'veritx_embed.cpp'),
                  str(source / 'libveritx_embed.a'), '-o', str(binary)]},
    ]
    build_script = REPO / 'scripts/build_native_coupled_diagnostic.py'
    build_record = {
        'schema_version': 1,
        'scope': 'LOCAL_BUILD_RECORD_NOT_ATTESTATION',
        'booksim_executable_sha256': pin(binary)['sha256'],
        'booksim_source_manifest_sha256': pin(source_manifests['booksim'])['sha256'],
        'driver_sha256': pin(driver)['sha256'],
        'builder_sha256': pin(build_script)['sha256'],
        'compiler': {**pin(compiler), 'version': subprocess.check_output(
            [compiler, '--version'], text=True).splitlines()[0]},
        'make': {**pin(make_tool), 'version': subprocess.check_output(
            [make_tool, '--version'], text=True).splitlines()[0]},
        'commands': booksim_commands,
    }
    build_record_path = out / 'booksim-build-provenance.json'
    build_record_path.write_text(json.dumps(build_record, indent=2) + '\n')
    multicast_config = {
        'files': {
            'booksim_executable': pin(binary),
            'booksim_source_manifest': pin(source_manifests['booksim']),
            'booksim_build_provenance': pin(build_record_path),
        },
        'host_flit_limit': 64,
        'max_engine_steps': 100000,
    }
    multicast_config_path = out / 'native-multicast-config.json'
    multicast_config_path.write_text(json.dumps(multicast_config, indent=2) + '\n')
    if not args.booksim_only:
        memory = json.loads((REPO / 'tracks/t3-topology/dse/examples/native_hbm2_config.json').read_text())
        files = {'booksim_executable': binary, 'booksim_library': source / 'libveritx_embed.a',
                 'booksim_source_manifest': source_manifests['booksim'], 'ramulator_extension': extensions[0],
                 'ramulator_library': ramulator / 'libramulator.so',
                 'ramulator_source_manifest': source_manifests['ramulator']}
        config = {'files': {k: pin(v) for k, v in files.items()}, 'ramulator_config': memory,
            'booksim_period_ps_num': 2000, 'booksim_period_ps_den': 1, 'memory_tck_ps': 1000,
            'owner_endpoint': 1, 'window_start': 4096, 'window_end': 4160, 'tx_bytes': 32,
            'host_reservation_slots': 2, 'max_memory_outstanding': 4,
            'host_flit_limit': 64, 'max_engine_steps': 100000}
        path = out / 'native-config.json'
        path.write_text(json.dumps(config, indent=2) + '\n')
    provenance = {'scope': 'DIAGNOSTIC_UNQUALIFIED_SOURCE_COPY', 'qualified': False,
        'python': sys.version, 'source_checkpoint': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'source_status': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=REPO, text=True),
        'commands': commands,
        'native_multicast_config': pin(multicast_config_path),
        'booksim_build_provenance': pin(build_record_path)}
    if not args.booksim_only:
        provenance['config'] = pin(path)
    (out / 'build-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(multicast_config_path if args.booksim_only else path)


if __name__ == '__main__':
    main()
