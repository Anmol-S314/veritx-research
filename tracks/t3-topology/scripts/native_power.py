"""Scoped BookSim power-model evidence for supported-sweep research comparisons.

The shipped technology file is a 2007 ITRS prediction for 32nm, not a silicon
calibration. Shared-wire estimates require the explicit electrical extension
and versioned runtime coverage; old partial logs are never promoted.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

# Additional families require runtime port/monitor coverage from the audited binary.
SHARED_FAMILIES = {"SROTA", "GEC_MECS", "GEC_HYBRID"}
COVERAGE_REQUIRED_FAMILIES = {"RING", "QTREE", "TREE4", "FLY"} | SHARED_FAMILIES
NATIVE_FAMILIES = {"MESH", "TORUS", "CONCENTRATED_MESH", "FAT_TREE", "FLATFLY", "CUSTOM"} | COVERAGE_REQUIRED_FAMILIES


def prepare_model(repo: Path, root: Path, binary: Path) -> dict:
    tech = repo / "third_party/booksim2/src/power/techfile.txt"
    raw = tech.read_bytes()
    values = {key: float(value) for key, value in re.findall(
        r"^\s*(\w+)\s*=\s*([\d.eE+-]+)\s*;", raw.decode(), re.M)}
    # Exact clock rule in Power_Module's constructor (not the project clock).
    fo4 = values['R'] * (3 * values['Cd'] + 12 * values['Cg'] + 12 * values['Cgdl'])
    clock_hz = 1 / (20 * fo4)
    if not math.isfinite(clock_hz) or clock_hz <= 0:
        raise ValueError('Invalid BookSim technology clock')
    tech_hash = hashlib.sha256(raw).hexdigest()
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    policy = 'native-full-swing-tapped-grid/v1'
    model_id = hashlib.sha256(f'{tech_hash}:{binary_hash}:128:{policy}'.encode()).hexdigest()
    model = {
        'model_id': model_id,
        'fidelity': 'BOOKSIM_NATIVE_MODEL',
        'technology': '2007 ITRS 32nm high-performance prediction; not silicon calibrated',
        'tech_source': 'third_party/booksim2/src/power/techfile.txt',
        'tech_sha256': tech_hash,
        'booksim_sha256': binary_hash,
        'clock_hz': clock_hz,
        'clock_rule': '1 / (20 * R * (3*Cd + 12*Cg + 12*Cgdl))',
        'channel_width_bits': 128,
        'wire_length_mm_per_latency_cycle': values['wire_length'],
        'energy_definition': 'native total W / model clock Hz * 1e12; network pJ/cycle, not pJ/packet',
        'limitations': 'Architectural data-path model, not silicon calibrated. No NIC/compute/DRAM, credit/control-wire costs or allocator/layout signoff. Ordinary wire length uses latency * tech wire_length; shared grid trunks use tech wire_length as router pitch with always-propagating full-swing data and one D2 isolation input per bit/tap. Repeaters/retiming are costed, not proof that simulated latency is physically feasible. Power counters span the full simulation.',
        'shared_wire_model': {
            'policy': policy, 'version': 1, 'router_pitch_mm': values['wire_length'],
            'geometry': 'union of collinear grid intervals between live source and taps, each interval counted once',
            'propagation': 'all trunk segments carry source activity; no early-stop or branch-gating savings',
            'receiver': 'one INVD2-equivalent isolation input per bit/tap; native input FIFO not duplicated',
        },
        'shared_coefficients': {
            'tap_bank_mm2': 128 * values['W_INVD2'] * values['H_INVD2'] * values['MetalPitch'] ** 2,
            'tap_dynamic_w_per_rate': 128 * .5 * 2 * (3 * values['Cg_pwr']) * values['Vdd'] ** 2 * clock_hz,
            'tap_bank_leakage_w': 128 * 2 * .5 * (values['IoffN'] + 2 * values['IoffP']) * values['Vdd'],
        },
        'area_coefficients': {
            'input_flit_mm2': 128 * values['H_SRAM'] * values['W_SRAM'] * values['MetalPitch'] ** 2,
            'crosspoint_mm2': (128 * 2 * values['MetalPitch']) ** 2,
            'output_port_mm2': 128 * values['W_DFQD1'] * values['H_DFQD1'] * values['MetalPitch'] ** 2,
        },
    }
    target = root / 'native-model'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'techfile.txt').write_bytes(raw)
    (target / 'model.json').write_text(json.dumps(model, indent=2) + '\n')
    return model


def _summary_value(text: str, label: str) -> float | None:
    matches = re.findall(rf'^- {re.escape(label)}:\s*([\d.eE+-]+)\s*$', text, re.M)
    try:
        value = float(matches[0]) if len(matches) == 1 else None
    except ValueError:
        return None
    return value if value is not None and math.isfinite(value) and value >= 0 else None


def coverage_audit(text: str, model: dict) -> dict:
    """Reconcile the modeled port graph, resource census and component totals."""
    version = _summary_value(text, 'Power Coverage Version')
    if version not in (1, 2):
        return {'status': 'ABSENT', 'reason': 'Runtime power-coverage proof missing; use the audited power binary'}
    labels = ['Config Supported', 'Routers', 'Modeled Channels', 'Duplicate Channels',
              'Unmodeled Inputs', 'Unmodeled Outputs', 'Endpoint Errors', 'Non-IQ Routers',
              'Monitor Errors', 'Total Inputs', 'Total Outputs', 'Crosspoints', 'Buffer Slots']
    if version == 2:
        labels += ['Shared Model Version', 'Shared Wires', 'Shared Taps', 'Shared Segments',
                   'Shared Active Tap Flits', 'Shared Geometry Errors']
    counts = {label: _summary_value(text, 'Power ' + label) for label in labels}
    if any(value is None or not value.is_integer() for value in counts.values()):
        return {'status': 'INCOMPLETE', 'reason': 'Runtime coverage counts missing or invalid'}
    counts = {key: int(value) for key, value in counts.items()}
    if counts['Unmodeled Outputs'] or counts['Unmodeled Inputs']:
        return {'status': 'INCOMPLETE', 'counts': counts, 'reason':
                f"Native power omits {counts['Unmodeled Outputs']} shared-wire outputs and "
                f"{counts['Unmodeled Inputs']} input taps; wire/tap electrical modeling is absent"}
    errors = ['Duplicate Channels', 'Endpoint Errors', 'Non-IQ Routers', 'Monitor Errors']
    if version == 2:
        errors.append('Shared Geometry Errors')
    if counts['Config Supported'] != 1 or any(counts[key] for key in errors):
        return {'status': 'INCOMPLETE', 'counts': counts, 'reason': 'Unsupported power config or live channel/monitor coverage error'}
    costs = re.findall(r'Network cost: subnet=\d+ routers=(\d+) input_ports=(\d+) output_ports=(\d+) crosspoints=(\d+) storage_flits=(\d+)', text)
    if len(costs) != 1 or tuple(counts[key] for key in ['Routers', 'Total Inputs', 'Total Outputs', 'Crosspoints', 'Buffer Slots']) != tuple(map(int, costs[0])):
        return {'status': 'INCOMPLETE', 'counts': counts, 'reason': 'Power census disagrees with live router resources'}
    coefficients = model.get('area_coefficients', {})
    rules = [('Input  Area', 'input_flit_mm2', 'Buffer Slots'),
             ('Switch  Area', 'crosspoint_mm2', 'Crosspoints'),
             ('Output  Area', 'output_port_mm2', 'Total Outputs')]
    for label, coefficient, count in rules:
        actual = _summary_value(text, label)
        expected = coefficients.get(coefficient, 0) * counts[count]
        if actual is None or expected <= 0 or not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-10):
            return {'status': 'INCOMPLETE', 'counts': counts, 'reason': f'{label} disagrees with technology and resource count'}
    power_parts = ['Channel Wire Power', 'Channel Clock Power', 'Channel Retiming Power', 'Channel Leakage Power',
                   'Input Read Power', 'Input Write Power', 'Input Leakage Power', 'Switch Power',
                   'Switch Control Power', 'Switch Leakage Power', 'Output DFF Power', 'Output Clk Power', 'Output Control Power']
    for total_label, parts in [('Total Power', power_parts), ('Total Area', ['Channel Area', 'Switch  Area', 'Input  Area', 'Output  Area'])]:
        values = [_summary_value(text, label) for label in parts]
        total = _summary_value(text, total_label)
        if total is None or any(value is None for value in values) or not math.isclose(total, sum(values), rel_tol=1e-8, abs_tol=1e-10):
            return {'status': 'INCOMPLETE', 'counts': counts, 'reason': f'{total_label} is not the sum of valid component outputs'}
    if version == 2:
        shared_error = _shared_coverage_error(text, counts, model)
        if shared_error:
            return {'status': 'INCOMPLETE', 'counts': counts, 'reason': shared_error}
    return {'status': 'COMPLETE', 'version': int(version), 'counts': counts,
            'scope': 'Runtime IQ data-path accounting, including shared trunks/taps when present; architectural electrical assumptions, not physical-layout or silicon qualification'}


def _shared_coverage_error(text: str, counts: dict, model: dict) -> str | None:
    wires, taps = counts['Shared Wires'], counts['Shared Taps']
    if counts['Shared Model Version'] != 1 or taps < wires or counts['Shared Segments'] != taps:
        return 'Shared wire/tap/segment census is inconsistent'
    if counts['Total Inputs'] - counts['Total Outputs'] != taps - wires:
        return 'Shared tap incidence disagrees with live router ports'
    labels = ['Shared Wire Length mm', 'Shared Trunk Area', 'Shared Tap Area', 'Shared Total Area',
              'Shared Trunk Power', 'Shared Tap Power', 'Shared Tap Leakage', 'Shared Total Power']
    values = {key: _summary_value(text, key) for key in labels}
    if any(value is None for value in values.values()):
        return 'Shared electrical component outputs are missing or invalid'
    if not wires:
        return None if not taps and not counts['Shared Active Tap Flits'] and all(value == 0 for value in values.values()) else 'Shared electrical output exists without a shared wire'
    pitch = model.get('shared_wire_model', {}).get('router_pitch_mm', 0)
    cycles = _summary_value(text, 'Completion Time')
    coefficients = model.get('shared_coefficients', {})
    if pitch <= 0 or values['Shared Wire Length mm'] + 1e-9 < taps * pitch or not cycles or values['Shared Trunk Area'] <= 0 or values['Shared Trunk Power'] <= 0:
        return 'Shared geometry, interval or trunk cost is invalid'
    expected = {
        'Shared Tap Area': coefficients.get('tap_bank_mm2', 0) * taps,
        'Shared Tap Power': coefficients.get('tap_dynamic_w_per_rate', 0) * counts['Shared Active Tap Flits'] / cycles,
        'Shared Tap Leakage': coefficients.get('tap_bank_leakage_w', 0) * taps,
        'Shared Total Area': values['Shared Trunk Area'] + values['Shared Tap Area'],
        'Shared Total Power': values['Shared Trunk Power'] + values['Shared Tap Power'] + values['Shared Tap Leakage'],
    }
    if not coefficients.get('tap_bank_mm2') or not coefficients.get('tap_dynamic_w_per_rate') or not coefficients.get('tap_bank_leakage_w'):
        return 'Shared receiver technology coefficients are missing'
    for key, value in expected.items():
        if not math.isclose(values[key], value, rel_tol=1e-8, abs_tol=1e-10):
            return f'{key} disagrees with independent shared-wire accounting'
    channel_area = _summary_value(text, 'Channel Area')
    channel_power = sum(_summary_value(text, key) for key in ['Channel Wire Power', 'Channel Clock Power', 'Channel Retiming Power', 'Channel Leakage Power'])
    if values['Shared Total Area'] > channel_area + 1e-9 or values['Shared Total Power'] > channel_power + 1e-9:
        return 'Shared costs are absent from the combined channel totals'
    return None


def power_evidence(text: str, family: str, status: str, returncode: int, model: dict | None) -> dict:
    result = {'native_power_w': None, 'native_area_mm2': None, 'native_energy_pj_per_cycle': None}
    if model is None:
        return {**result, 'native_model': {'status': 'NOT_REQUESTED', 'reason': 'Re-run sweep_supported.py --native-power'}}
    audit = coverage_audit(text, model)
    if family not in NATIVE_FAMILIES:
        reason = audit.get('reason') if audit['status'] == 'INCOMPLETE' else 'Shared-wire or unaudited family: native channel accounting is not qualified for this realization'
        return {**result, 'native_model': {**model, 'status': 'UNSUPPORTED', 'reason': reason, 'coverage_audit': audit}}
    if status != 'ok' or returncode != 0:
        return {**result, 'native_model': {**model, 'status': 'UNAVAILABLE', 'reason': 'No successful simulator run'}}
    if audit['status'] == 'INCOMPLETE' or (family in COVERAGE_REQUIRED_FAMILIES and audit['status'] != 'COMPLETE'):
        return {**result, 'native_model': {**model, 'status': 'UNSUPPORTED', 'reason': audit['reason'], 'coverage_audit': audit}}
    if family in SHARED_FAMILIES and audit.get('version') != 2:
        return {**result, 'native_model': {**model, 'status': 'UNSUPPORTED',
                'reason': 'Shared-wire electrical coverage requires the v2 native power binary', 'coverage_audit': audit}}
    power, area = _summary_value(text, 'Total Power'), _summary_value(text, 'Total Area')
    if power is None or area is None or power <= 0 or area <= 0:
        return {**result, 'native_model': {**model, 'status': 'UNAVAILABLE', 'reason': 'Native power/area summary missing or invalid'}}
    return {
        'native_power_w': power,
        'native_area_mm2': area,
        'native_energy_pj_per_cycle': power / model['clock_hz'] * 1e12,
        'native_model': {**model, 'status': 'AVAILABLE', 'coverage_audit': audit},
    }
