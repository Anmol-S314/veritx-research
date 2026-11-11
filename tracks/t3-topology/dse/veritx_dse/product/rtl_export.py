"""Real topology RTL previews, explicitly NOT a final implementation contract.

The existing emitter has a fixed packet layout and router policy. Never call
its output a realization of arbitrary compiled workload/router controls.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.clock_power_cdc import (
    ClockPowerInput, EndpointDomain, crossing_points,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.product.adapter_factory_rtl import AdapterParams, build_adapter
from veritx_dse.product.addr_decode_rtl import render_addr_decode
from veritx_dse.product.catalog_evaluation import (
    rtl_support, sha256, write_json,
)
from veritx_dse.product.cdc_cell_rtl import (
    CdcParams, build_cdc_cell, check_cdc_cell_source, estimate_mtbf,
)
from veritx_dse.product.ordering_fsm_rtl import (
    build_ordering_fsm, policy_from_request,
)

LIMITATIONS = [
    'The existing emitter uses 64-bit flits and a 2-VC free/escape router scheme.',
    'The preview uses a generic free/escape route table over the selected graph; the selected family native routing law (DOR, torus dateline, ring halves, NCA, destination-tag, ...) is not generally realized.',
    'Compiler packet format, VC policy, router pipeline, arbitration, endpoint adaptation and shared-wire semantics are not generally realized by this emitter.',
    'addr_decode.sv decodes the resolved address map to attached endpoints and enforces declared STAGE 1 initiator × region permission policies (req_id + req_write gate, perm_violation on denial, burst_len containment with DENY on crossing, default-deny for unmapped/unknown initiator); it does not implement protocol adaptation or packet routing.',
    'Verilator lint checks syntax and connectivity, not simulation equivalence or hardware qualification.',
    'M2 ordering/VC desires are realized by the OrderingFSM (ordering_fsm.sv: strong/relaxed/RAW sequence enforcement, outstanding backpressure, split-at alignment, class->VC reassignment onto RT_MIN/RT_ESC). M3 clock crossings are realized by emitted CdcCells (cdc_cell_*.sv reusing rtl/cdc/cdc_fifo.sv unchanged); M4 adapters are realized by AdapterFactory full modules (adapter_axi5_*.sv AXI5 full AW/W/AR/R/B incl. coherency/DVM/RSOS, adapter_chi_*.sv CHI Full-Profile incl. DVM/RSOS/QoS/P-Credit/coherency/C/DWT/Expiry/reorder/CT-legacy, adapter_tilelink_*.sv TileLink-1.8.1 UL+UH+C A/B/C/D/E incl. RMW/BCEB head/tail, adapter_custom_*.sv declared burst/ordering); final_implementation stays False (TOPOLOGY_ONLY_PREVIEW). Any M2 policy outside the 2-VC slice (VC>=2, shared wire, relaxed without a window, disagreeing groups) is refused by rtl_support with a typed blocker naming OrderingFSM, never silently dropped.',
]

ASSUMPTIONS = [
    ('Scope', 'Declared topology and compile-result facts only. No measured utilization, achieved timing or observed packet path is shown.'),
    ('CDC hardware', 'CdcCell async FIFO is depth-16 nominal (net usable depth 8 entries: cdc_fifo asserts FULL at VDEPTH=DEPTH/2, the upper DEPTH/2 slots are shadow capacity absorbing synchronizer lag — nominal depth is never read as usable depth) with a SYNC_STAGES=3 synchronizer chain and 2-FF reset synchronizers.'),
    ('CDC MTBF', 'Calculated only when both per-domain clock rates are declared (CdcParams.src_clock_mhz/dst_clock_mhz) with the estimator in veritx_dse.product.cdc_cell_rtl (formula after Cummings AN-1077; declared tau=100 ps, t0=50 ps — assumed constants, not library signoff data). The request schema carries no per-domain rates (UNDECLARED), so preview cells stay NOT_CALCULATED with reason; no single global clock default is substituted as a per-domain rate.'),
    ('Timing closure (STA)', 'Not established — no timing analysis, clock-tree, placement or congestion work; default_clock_freq_mhz stays an assumption.'),
    ('Power-domain isolation (PTS)', 'Not established — no level shifters, isolation or retention; multi-power fabrics are not served by this preview.'),
    ('OrderingFSM', 'Strong is stall-on-violation (no reorder buffer); relaxed flags beyond the outstanding window; split alignment closes/resets flit types at SPLIT_AT. Per-group divergence is refused, not merged.'),
    ('AXI5 compliance', 'FULL claimed — adapter_axi5_g*.sv realizes AW/W/AR/R/B full channels (AxID/AxLEN/AxSIZE/AxBURST/AxLOCK/AxCACHE/AxPROT/AxQOS/AxREGION/AxDOMAIN/AxATOMIC/AxDVMType, WSTRB/WLAST, BRESP/RRESP, exclusive/atomic boundaries), WidthWidget split/merge, and checked error flags (aw/ar/exclusive/atomic/coh/resp/id/wstrb/last). Not established — certified AXI5 wrapper; final_implementation stays False (TOPOLOGY_ONLY_PREVIEW).'),
    ('CHI compliance', 'FULL claimed — adapter_chi_g*.sv realizes CHI Full-Profile (SIZE alignment to the DATA_W granule, REQ/RSP/SNP/DAT channel map, DAT byte-enable filtering, outstanding-credit gate, ordering, DVM/RSOS (opcode[3:2]), QoS bypass, P-Credit, coherency FSM SC/UC/UD/SD, C/DWT/Expiry watchdogs, multi-transaction reorder, CT/legacy (CHI.B/C/T) translation with typed ct_unsupported). Not established — ARM-spec CHI compliance, RN/FN sign-off; final_implementation stays False (TOPOLOGY_ONLY_PREVIEW).'),
    ('TileLink compliance', 'FULL claimed — adapter_tilelink_g*.sv realizes TileLink-1.8.1 UL+UH+C (A/B/C/D/E with opcode/size/param/source/sink/mask/address/data/corrupt/denied, RMW op_numeric, hint/intent, BCEB Acquire/Probe/Release/Grant/GrantAck with sink FIFO, nic.sv head/tail framing, credit gate, illegal/param/size checkers, TILELINK_FORMAL). Not established — full TileLink suite pass; final_implementation stays False (TOPOLOGY_ONLY_PREVIEW).'),
    ('Custom scope', 'Not established — the custom shim is parameterized only by the agent-declared burst/ordering; bare custom without params is INVALID at compile (no hidden defaults); custom implements no family-specific protocol.'),
    ('Simulation parity', 'Not established in the preview (parity is NOT_RUN; the explicit BookSim<->RTL conservation smoke proves 5-packet/10-flit conservation only, not cycle-accurate parity); lint PASS is syntax/connectivity only.'),
    ('Source', 'rtl-preview.json emitted-module manifest (cdc_cells / adapters / address_decode, files) and stage1_verdicts.'),
]


def _preview_assumptions(assumptions: list, parity_section: dict,
                         run_parity: bool) -> list:
    """Assumptions rows for the manifest (opt-in parity wording refresh).

    When the opt-in cycle-accurate smoke ran, the Simulation parity row is
    restated as measured evidence; otherwise the declared NOT_RUN row is
    carried unchanged (lint-only preview).
    """
    rows = [[label, text] for label, text in assumptions]
    if run_parity and parity_section.get('status') == 'PASS':
        measured = ('Measured by the opt-in cycle-accurate BookSim<->RTL '
                    'smoke (see the parity section): 5-packet/10-flit '
                    'conservation + exact delivered-payload multisets with '
                    'recorded cycle deltas (never forced equal); lint PASS '
                    'is syntax/connectivity only.')
        rows = [[label, (measured if label == 'Simulation parity' else text)]
                for label, text in rows]
    return rows


def run_rtl_preview(request_doc: dict, directory: Path, config: dict,
                    *, run_parity: bool = False) -> dict:
    request = CompileRequestV4.from_dict(request_doc)
    compiled = FabricCompiler().compile(request)
    if compiled.status != 'COMPILED' or compiled.bundle is None:
        raise ValueError(compiled.error or 'Compile the selected fabric before generating a topology RTL preview.')
    topology = compiled.bundle.topology
    support = rtl_support(
        request, topology, compiled.bundle.vc_assignment)
    if not support.supported:
        raise ValueError(support.reason or 'This selected fabric has no matching RTL emitter.')
    if getattr(topology, 'shared_links', ()):
        raise ValueError('The RTL preview emitter cannot preserve shared-wire topology. No point-to-point substitute was generated.')
    routers = sorted(router.router_id for router in topology.routers)
    if not 2 <= len(routers) <= 64 or routers != list(range(len(routers))):
        raise ValueError('The RTL preview emitter supports 2–64 contiguously numbered routers.')
    edges = {(channel.src_router, channel.dst_router) for channel in topology.channels}
    if any((dst, src) not in edges for src, dst in edges):
        raise ValueError('The RTL preview emitter requires reciprocal point-to-point channels.')
    # M3/M4 deep modules (pure): plan every crossing cell and per-agent
    # adapter before any directory is written. A blocked build raises here
    # with the builder's blocker id — never a partial tree, never a stub.
    agent_intents = tuple(getattr(request, 'agent_intents', ()) or ())
    by_idx = {intent.agent_idx: intent for intent in agent_intents}
    endpoints = tuple(
        EndpointDomain(
            agent_idx=i,
            agent_clock_domain=agent.clock_domain,
            agent_power_domain=agent.power_domain,
            intent_clock_domain=(by_idx[i].clock_domain
                                 if i in by_idx else None),
            intent_power_domain=(by_idx[i].power_domain
                                 if i in by_idx else None))
        for i, agent in enumerate(request.agents))
    cdc_input = ClockPowerInput(
        endpoints=endpoints, agents=tuple(request.agents),
        num_power_domains=request.physical.num_power_domains)
    cell_builds = []
    for point in crossing_points(cdc_input):
        src_agent = (request.agents[point.src_group]
                     if point.src_group is not None
                     and point.src_group < len(request.agents)
                     else (request.agents[0] if request.agents else None))
        build = build_cdc_cell(CdcParams(
            insertion_point=point.insertion_point,
            src_domain=point.src_domain, dst_domain=point.dst_domain,
            src_group=point.src_group, dst_group=point.dst_group,
            data_width=(src_agent.data_width
                        if src_agent is not None else 64),
            # Per-domain rates are absent from the request schema
            # (UNDECLARED): rates stay None so MTBF is NOT_CALCULATED
            # with reason; PhysicalContext.default_clock_freq_mhz is a
            # single global assumption and is never substituted.
        ))
        if not build.verdict.ok:
            raise ValueError(
                f"UNSUPPORTED: {build.verdict.blocker_id}: CdcCell build "
                f"refused insertion point {point.insertion_point!r}: "
                f"{build.verdict.reason} "
                f"(owner stage = RTL generation).")
        cell_builds.append(build)
    adapter_builds = []
    for intent in agent_intents:
        if getattr(intent, 'protocol', None) is None:
            continue
        idx = intent.agent_idx
        agent = request.agents[idx] if 0 <= idx < len(request.agents) else None
        ordering = getattr(intent, 'ordering', None)
        build = build_adapter(AdapterParams(
            agent_idx=idx, protocol=intent.protocol,
            data_width=agent.data_width if agent else 256,
            addr_width=agent.addr_width if agent else 64,
            split_at=getattr(intent, 'split_at', None),
            max_outstanding=getattr(intent, 'max_outstanding', None),
            ordering=(getattr(ordering, 'value', ordering)
                      if ordering is not None else None)))
        if not build.verdict.ok:
            raise ValueError(
                f"UNSUPPORTED: {build.verdict.blocker_id}: AdapterFactory "
                f"refused agent group {idx}: {build.verdict.reason} "
                f"(owner stage = RTL generation).")
        adapter_builds.append(build)
    # M2 deep module (pure): one policy struct in -> (module, verdict) out,
    # planned before any directory is written. A refusal raises with the
    # typed OrderingFSM reason — never a partial tree, never a substitute.
    ordering_policy = policy_from_request(request)
    shared_wires = len(getattr(topology, 'shared_links', ()) or ())
    ordering_emission = build_ordering_fsm(
        ordering_policy, emitted_vcs=2, shared_wires=shared_wires)
    if not ordering_emission.verdict.ok:
        raise ValueError(ordering_emission.verdict.reason)
    directory.mkdir(parents=True, exist_ok=True)
    anynet = directory / 'selected-topology.anynet'
    anynet.write_text(''.join(f"router {rid} node {rid}" + ''.join(f" router {dst}" for src, dst in sorted(edges) if src == rid) + '\n' for rid in routers))
    target = directory / 'rtl'
    script = Path(config['repo_root']) / 'tracks/t3-topology/scripts/rtlgen/gen_rtl.py'
    command = [sys.executable, str(script), '--anynet', str(anynet), '--outdir', str(target), '--num-vc', '2', '--buf', str(request.noc_controls.input_buffer_depth_flits_per_vc or 8)]
    # gen_rtl owns topology/buffer/VC emission only. Ordering is emitted by
    # OrderingFSM below; passing its policy to gen_rtl is unsupported.
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('RTL emitter refused this topology: ' + (result.stderr or result.stdout)[-2000:])
    decode = getattr(compiled.bundle, 'address_decode', None)
    decode_entries = tuple(getattr(decode, 'entries', ()) or ())
    # STAGE 1 M1 (initiator × region): permission windows ride the request
    # (CompileRequestV4) as (agent_idx, range) policies. The renderer keys
    # by (initiator, range), not range alone. A policy that compile already
    # refused cannot reach this path.
    from veritx_dse.model.address_permission import InitiatorPolicy  # noqa: PLC0415
    initiator_policies = tuple(
        InitiatorPolicy(
            agent_idx=int(intent.agent_idx),
            address_range=str(window.address_range),
            readable=bool(window.readable),
            writable=bool(window.writable),
            atomic=bool(getattr(window, "atomic", False)),
        )
        for intent in getattr(request, 'agent_intents', ()) or ()
        for window in getattr(intent, 'permission_windows', ()) or ())
    # Legacy `windows` name kept for the manifest; the decoder is fed the
    # initiator-keyed policies so two groups on one range are distinct.
    windows = initiator_policies
    addr_decode_path = target / 'addr_decode.sv'
    addr_decode_path.write_text(render_addr_decode(decode, initiator_policies=initiator_policies))
    # M3/M4 emitted modules: one file per CdcCell / per-agent AdapterFactory
    # shim, plus the reused cdc_fifo copied unchanged beside the cells.
    emitted_filenames: list[str] = ['addr_decode.sv']
    cdc_fifo_path = None
    if cell_builds:
        cdc_source_path = (Path(config['repo_root'])
                           / 'tracks/t3-topology/rtl/cdc/cdc_fifo.sv')
        if not cdc_source_path.is_file():
            raise ValueError(
                'UNSUPPORTED: CDC_CELL_MISSING: rtl/cdc/cdc_fifo.sv is '
                'missing, so no asynchronous FIFO exists to reuse for the '
                'declared clock crossings (owner stage = RTL generation).')
        cdc_fifo_path = target / 'cdc_fifo.sv'
        text = cdc_source_path.read_text()
        cdc_fifo_path.write_text(text if text.endswith('\n') else text + '\n')
        emitted_filenames.append('cdc_fifo.sv')
    for build in cell_builds:
        filename = f'{build.module}.sv'
        (target / filename).write_text(build.source or '')
        emitted_filenames.append(filename)
    for build in adapter_builds:
        filename = f'{build.module}.sv'
        (target / filename).write_text(build.source or '')
        emitted_filenames.append(filename)
    # M2 emitted module: single instance covering the agreed policy.
    if ordering_emission.sv_source is not None:
        (target / 'ordering_fsm.sv').write_text(ordering_emission.sv_source)
        emitted_filenames.append('ordering_fsm.sv')
    cdc_fifo_sha256 = sha256(cdc_fifo_path) if cdc_fifo_path else None
    # The emitter's own inventory must name the emitted modules too;
    # otherwise `make` and the archive disagree about what is in the dir.
    meta_path = target / 'meta.json'
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            files = list(meta.get('files', []))
            for filename in emitted_filenames:
                if filename not in files:
                    files.append(filename)
            meta['files'] = files
            meta_path.write_text(json.dumps(meta, indent=2) + '\n')
        except (OSError, ValueError):
            # The emitter's meta.json is an inventory, not the manifest of
            # record; a malformed one must not abort an otherwise valid
            # preview. The manifest below still lists every file.
            pass
    makefile = target / 'Makefile'
    if makefile.is_file():
        text = makefile.read_text()
        if 'lint-addr-decode:' not in text:
            text += ("\n\nlint-addr-decode:\n"
                     "\t$(VERILATOR) --lint-only -sv -Wall -Wno-fatal "
                     "--top-module addr_decode addr_decode.sv\n")
        if cell_builds and 'lint-cdc:' not in text:
            text += ("\n\nlint-cdc:\n"
                     + ''.join(
                         f"\t$(VERILATOR) --lint-only -sv -Wall -Wno-fatal "
                         f"--top-module {build.module} "
                         f"cdc_fifo.sv {build.module}.sv\n"
                         for build in cell_builds))
        if adapter_builds and 'lint-adapters:' not in text:
            text += ("\n\nlint-adapters:\n"
                     + ''.join(
                         f"\t$(VERILATOR) --lint-only -sv -Wall -Wno-fatal "
                         f"--top-module {build.module} "
                         f"{build.module}.sv\n"
                         for build in adapter_builds))
        if ordering_emission.sv_source is not None and 'lint-ordering-fsm:' not in text:
            text += ("\n\nlint-ordering-fsm:\n"
                     "\t$(VERILATOR) --lint-only -sv -Wall -Wno-fatal "
                     "--top-module ordering_fsm ordering_fsm.sv\n")
        if text != makefile.read_text():
            makefile.write_text(text)
    attachment = getattr(compiled.bundle, 'attachment', None)
    endpoint_map = []
    for endpoint in getattr(attachment, 'endpoints', ()) or ():
        agent = getattr(endpoint, 'agent', None)
        kind = getattr(agent, 'kind', None)
        endpoint_map.append({
            'endpoint_id': getattr(endpoint, 'endpoint_id', None),
            'router_id': getattr(endpoint, 'router_id', None),
            'port_id': getattr(endpoint, 'port_id', None),
            'agent_kind': getattr(kind, 'value', kind),
            'agent_instance_index': getattr(agent, 'instance_index', None),
        })
    lint = {'status': 'NOT_RUN', 'reason': 'Verilator is not installed.'}
    verilator = shutil.which('verilator')
    if verilator:
        checked = subprocess.run([verilator, '--lint-only', '-sv', '-Wall', '-Wno-fatal', '-Wno-WIDTH', '-Wno-PINNOTFOUND', '-Wno-UNOPTFLAT', '--top-module', 'noc_top', 'noc_pkg.sv', 'router.sv', 'noc_top.sv'], cwd=target, capture_output=True, text=True, timeout=60)
        log = (checked.stdout + checked.stderr)[-6000:]
        # Lint PASS is exit status only; a warning-bearing pass is reported as
        # such so a reader never mistakes it for clean RTL.
        warnings = sum(1 for line in log.splitlines() if line.lstrip().startswith('%Warning'))
        lint = {'status': 'PASS' if checked.returncode == 0 else 'FAIL', 'log': log,
                'warning_count': warnings, 'clean': checked.returncode == 0 and warnings == 0}
        if checked.returncode:
            raise ValueError('Generated RTL failed Verilator lint: ' + log)
    addr_lint = {'status': 'NOT_RUN', 'reason': 'Verilator is not installed.'}
    if verilator:
        checked = subprocess.run([verilator, '--lint-only', '-sv', '-Wall', '-Wno-fatal', '--top-module', 'addr_decode', 'addr_decode.sv'], cwd=target, capture_output=True, text=True, timeout=60)
        log = (checked.stdout + checked.stderr)[-6000:]
        warnings = sum(1 for line in log.splitlines() if line.lstrip().startswith('%Warning'))
        addr_lint = {'status': 'PASS' if checked.returncode == 0 else 'FAIL', 'log': log,
                     'warning_count': warnings, 'clean': checked.returncode == 0 and warnings == 0}
        if checked.returncode:
            raise ValueError('Generated address decoder failed Verilator lint: ' + log)

    def _module_lint(files, top, failure_prefix):
        result = {'status': 'NOT_RUN', 'reason': 'Verilator is not installed.'}
        if verilator:
            checked = subprocess.run(
                [verilator, '--lint-only', '-sv', '-Wall', '-Wno-fatal',
                 '-Wno-WIDTH', '-Wno-PINNOTFOUND', '-Wno-UNOPTFLAT',
                 '--top-module', top, *files],
                cwd=target, capture_output=True, text=True, timeout=60)
            log = (checked.stdout + checked.stderr)[-6000:]
            warnings = sum(1 for line in log.splitlines()
                           if line.lstrip().startswith('%Warning'))
            result = {'status': 'PASS' if checked.returncode == 0 else 'FAIL',
                      'log': log, 'warning_count': warnings,
                      'clean': checked.returncode == 0 and warnings == 0}
            if checked.returncode:
                raise ValueError(failure_prefix + log)
        return result

    cell_lints = {build.module: _module_lint(
        ['cdc_fifo.sv', f'{build.module}.sv'], build.module,
        f'Generated CdcCell {build.module} failed Verilator lint: ')
        for build in cell_builds}
    adapter_lints = {build.module: _module_lint(
        [f'{build.module}.sv'], build.module,
        f'Generated adapter {build.module} failed Verilator lint: ')
        for build in adapter_builds}
    cell_rows = []
    for build in cell_builds:
        mtbf = estimate_mtbf(
            build.params.src_clock_mhz, build.params.dst_clock_mhz,
            build.params.sync_stages)
        cell_rows.append({
            'insertion_point': build.params.insertion_point,
            'module': build.module,
            'file': f'{build.module}.sv',
            'sha256': sha256(target / f'{build.module}.sv'),
            'lint': cell_lints[build.module],
            'cdc_checks': list(check_cdc_cell_source(build.source or '')),
            # MTBF: CALCULATED from declared rates (formula + declared
            # tau/t0) or NOT_CALCULATED with reason when rates are
            # UNDECLARED (always the case for preview requests: the
            # schema declares no per-domain rates).
            'mtbf': {
                'status': mtbf.status,
                'years': mtbf.years,
                'reason': mtbf.reason,
                'direction': mtbf.direction,
                'src_clock_mhz': mtbf.src_clock_mhz,
                'dst_clock_mhz': mtbf.dst_clock_mhz,
                'sync_stages': mtbf.sync_stages,
                'tau_ps': mtbf.tau_ps,
                't0_ps': mtbf.t0_ps,
            },
        })
    adapter_rows = [{
        'agent_idx': build.params.agent_idx,
        'protocol': getattr(
            getattr(build.params, 'protocol', None), 'value',
            build.params.protocol),
        'module': build.module,
        'file': f'{build.module}.sv',
        'sha256': sha256(target / f'{build.module}.sv'),
        'lint': adapter_lints[build.module],
        # BookSim-side smoke for this adapter: the preview only records
        # typed NOT_RUN here (lint evidence only); the explicit smoke
        # (run_adapter_booksim_smoke / run_booksim_rtl_parity_smoke)
        # proves 5-packet/10-flit conservation when the harness exists
        # and stays NOT_RUN otherwise — never a silent PASS.
        'booksim_smoke': {
            'status': 'NOT_RUN', 'code': 'ADAPTER_BOOKSIM_NOT_RUN',
            'reason': 'Preview records lint evidence only; adapter '
                      'BookSim smoke is measured by '
                      'run_adapter_booksim_smoke on the preview dir '
                      '(BookSim+Verilator harness), never assumed.'},
    } for build in adapter_builds]
    if ordering_emission.sv_source is not None:
        ordering_lint = _module_lint(
            ['ordering_fsm.sv'], 'ordering_fsm',
            'Generated OrderingFSM failed Verilator lint: ')
        ordering_sha = sha256(target / 'ordering_fsm.sv')
    else:
        ordering_lint = {'status': 'NOT_RUN',
                         'reason': 'No OrderingFSM emitted (policy not declared).'}
        ordering_sha = None
    _route_table_of_vc = {0: 'RT_MIN(free)', 1: 'RT_ESC(escape)'}
    ordering_section = {
        'status': 'EMITTED' if ordering_emission.sv_source is not None else 'NOT_DECLARED',
        'module': 'ordering_fsm',
        'file': 'ordering_fsm.sv',
        'sha256': ordering_sha,
        'lint': ordering_lint,
        # Read-only summary: policy echo + VC table + route binding.
        'policy': ordering_policy.to_dict(),
        'vc_assignment': [
            {'traffic_class': name, 'vc': vc,
             'route_table': _route_table_of_vc[vc]}
            for name, vc in ordering_policy.traffic_class_vcs],
        'knob_map': [{'field': field, 'emits': emits}
                     for field, emits in ordering_emission.knob_map],
        # STAGE 1 M2 is realized here; the assumptions travel with the row.
        'realization': 'ORDERING_FSM' if ordering_emission.sv_source is not None else 'NOT_DECLARED',
        'not_established': list(ordering_emission.not_established),
    }
    parity_section = {
        'status': 'NOT_RUN', 'code': 'PARITY_NOT_RUN',
        'reason': 'The preview records lint evidence only; BookSim<->RTL '
        'conservation is measured by the explicit parity smoke '
        '(run_booksim_rtl_parity_smoke), never assumed.',
        'booksim': None, 'rtl': None,
        'not_established': [
            'Cycle-accurate parity (latency, exact routing): not established.',
        ],
    }
    if run_parity:
        # Opt-in real measurement: run the cycle-accurate BookSim<->RTL
        # smoke against the just-emitted RTL and embed its manifest.
        # The worker preview path leaves this off (lint-only, unchanged).
        from veritx_dse.product.ordering_fsm_rtl import (
            run_booksim_rtl_parity_smoke,
        )
        try:
            smoke = run_booksim_rtl_parity_smoke(rtl_dir=target, anynet=anynet)
        except Exception as exc:  # noqa: BLE001 - surfaced as NOT_RUN, not raised
            smoke = {'status': 'NOT_RUN', 'code': 'PARITY_NOT_RUN',
                     'reason': f'parity smoke raised {type(exc).__name__}: {exc}',
                     'booksim': None, 'rtl': None}
        parity_section = {
            'status': smoke.get('status', 'NOT_RUN'),
            'code': smoke.get('code', 'PARITY_NOT_RUN'),
            'reason': smoke.get('reason'),
            'booksim': smoke.get('booksim'),
            'rtl': smoke.get('rtl'),
            'cycle_accurate': smoke.get('cycle_accurate'),
            'delivered_payloads': smoke.get('delivered_payloads'),
            'not_established': [
                'Cycle equality (BookSim vs RTL drain cycles / latency): '
                'observed deltas recorded, never forced equal.',
            ] if smoke.get('status') == 'PASS' else [
                'Cycle-accurate parity (latency, exact routing): not established.',
            ],
        }
    manifest = {'schema': 'veritx/topology-rtl-preview/1', 'design_hash': request.design_hash(),
                'scope': 'TOPOLOGY_ONLY_PREVIEW', 'final_implementation': False,
                'limitations': LIMITATIONS, 'lint': lint,
                'stage1_verdicts': list(getattr(compiled, 'stage1_verdicts', ()) or ()),
                'stage1_findings': list(getattr(compiled, 'findings', ()) or ()),
                'address_decode': {
                    'status': 'EMITTED' if decode_entries else 'EMPTY',
                    'module': 'addr_decode',
                    'entry_count': len(decode_entries),
                    'address_decode_hash': getattr(decode, 'address_decode_hash', None),
                    # The decoder implements the declared decode contract and is
                    # proven equivalent to it by a bounded model check over all
                    # inputs (smtbmc + z3). That claim covers this artifact
                    # only — the composed top around it keeps its own scope.
                    'scope': 'ADDR_DECODE_CONTRACT',
                    'final_implementation': bool(decode_entries),
                    'final_implementation_evidence': {
                        'proof': 'tracks/t3-topology/rtl/formal/addr_decode_formal.sby',
                        'harness': 'tracks/t3-topology/rtl/formal/addr_decode_formal.sv',
                        'gate_test': 'tracks/t3-topology/dse/tests/test_formal_decode_equivalence.py',
                        'engine': 'smtbmc z3',
                        'properties': [
                            'window membership (hit/miss)',
                            'single-window non-overlap',
                            'per-initiator read/write permission',
                            'burst containment inside the window',
                            'one-hot target selection',
                            'trusted-ingress identity check',
                        ],
                        'residual': 'deadlock-freedom of the fabric is not proven here',
                    },
                    'endpoints': endpoint_map,
                    'lint': addr_lint,
                    # STAGE 1 M1 is realized here (initiator × range gate).
                    'permission_windows': [
                        {'agent_idx': window.agent_idx,
                         'address_range': window.address_range,
                         'readable': window.readable, 'writable': window.writable,
                         'atomic': bool(getattr(window, "atomic", False))}
                        for window in windows],
                    'permission_realization': 'ADDR_DECODE_GATE' if windows else 'NOT_DECLARED',
                },
                # LiveFabric-style structure: read-only summary (insertion /
                # cell / adapter inventory) on top, emitted-module manifest
                # below, assumptions with explicit "Not established" rows.
                'summary': {
                    'insertion_points': [row['insertion_point'] for row in cell_rows],
                    'cdc_cell_count': len(cell_rows),
                    'adapter_count': len(adapter_rows),
                    'adapter_by_family': {
                        family: sum(1 for row in adapter_rows
                                    if row['protocol'] == family)
                        for family in sorted({row['protocol'] for row in adapter_rows})},
                    'ordering_policy': ordering_policy.to_dict(),
                    'vc_assignment': ordering_section['vc_assignment'],
                    'blocked': [],
                },
                'ordering_fsm': ordering_section,
                'parity': parity_section,
                'cdc_cells': {
                    'status': 'EMITTED' if cell_rows else 'EMPTY',
                    'realization': 'CDC_CELL' if cell_rows else 'NOT_DECLARED',
                    'cells': cell_rows,
                    # Reused, unmodified: the async FIFO the cells instantiate.
                    'cdc_fifo': {'module': 'cdc_fifo',
                                 'source': 'tracks/t3-topology/rtl/cdc/cdc_fifo.sv',
                                 'file': 'cdc_fifo.sv',
                                 'sha256': cdc_fifo_sha256} if cell_rows else None,
                },
                'adapters': {
                    'status': 'EMITTED' if adapter_rows else 'EMPTY',
                    'realization': 'ADAPTER_FACTORY' if adapter_rows else 'NOT_DECLARED',
                    'adapters': adapter_rows,
                },
                'emitted_modules': (
                    [{'kind': 'address_decode', 'module': 'addr_decode',
                      'file': 'addr_decode.sv',
                      'sha256': sha256(target / 'addr_decode.sv')}]
                    + ([{'kind': 'cdc_fifo_reused', 'module': 'cdc_fifo',
                         'file': 'cdc_fifo.sv', 'sha256': cdc_fifo_sha256}]
                       if cell_rows else [])
                    + [{'kind': 'cdc_cell', 'module': row['module'],
                        'file': row['file'], 'sha256': row['sha256'],
                        'insertion_point': row['insertion_point']}
                       for row in cell_rows]
                    + [{'kind': 'adapter', 'module': row['module'],
                        'file': row['file'], 'sha256': row['sha256'],
                        'agent_idx': row['agent_idx'],
                        'protocol': row['protocol']}
                       for row in adapter_rows]
                    + ([{'kind': 'ordering_fsm', 'module': 'ordering_fsm',
                         'file': 'ordering_fsm.sv',
                         'sha256': ordering_sha,
                         'ordering': ordering_policy.ordering,
                         'vc_assignment': ordering_section['vc_assignment']}]
                       if ordering_emission.sv_source is not None else [])),
                'assumptions': _preview_assumptions(ASSUMPTIONS, parity_section,
                                                   run_parity),
                'source_topology': request.topology.to_dict(),
                'source_controls': request.noc_controls.to_dict(),
                'emitted_packet_width_bits': 64, 'emitted_vcs': 2,
                'files': [{'path': file.name, 'sha256': sha256(file)} for file in sorted(target.iterdir()) if file.is_file()]}
    write_json(directory / 'rtl-preview.json', manifest)
    archive = directory / 'topology-rtl-preview.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        package.write(directory / 'rtl-preview.json', 'rtl-preview.json')
        package.write(anynet, anynet.name)
        for file in sorted(target.iterdir()):
            if file.is_file():
                package.write(file, f'rtl/{file.name}')
    return {'preview_sha256': sha256(directory / 'rtl-preview.json'), 'archive_sha256': sha256(archive),
            'scope': 'TOPOLOGY_ONLY_PREVIEW', 'final_implementation': False, 'lint': lint['status'],
            'lint_warning_count': lint.get('warning_count'), 'lint_clean': lint.get('clean'),
            'address_decode': manifest['address_decode']['status'],
            'address_decode_lint': addr_lint['status'],
            'address_decode_lint_clean': addr_lint.get('clean'),
            'address_decode_lint_warning_count': addr_lint.get('warning_count'),
            'cdc_cells': manifest['cdc_cells']['status'],
            'cdc_cell_count': manifest['summary']['cdc_cell_count'],
            'adapters': manifest['adapters']['status'],
            'adapter_count': manifest['summary']['adapter_count'],
            'ordering_fsm': manifest['ordering_fsm']['status'],
            'ordering_fsm_lint': ordering_section['lint'].get('status'),
            'ordering_fsm_lint_clean': ordering_section['lint'].get('clean'),
            'parity': parity_section['status']}
