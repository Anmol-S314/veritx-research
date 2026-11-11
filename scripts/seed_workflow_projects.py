#!/usr/bin/env python3
"""Create non-destructive, idempotent gateway workflow fixtures; never deletes projects."""
import json
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:8099/api/v1'
OUTPUT = Path(__file__).resolve().parents[1] / 'apps/studio/prototype/.tmp/workflow-projects.json'


def api(path, body=None, method=None):
    request = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main():
    existing = {row['project']['name']: row for row in api('/projects')['projects']}
    scenarios = [
        ('01 · Dense decode · measured baseline', 'workload', 'qwen3-32b-tp2-16tiles', True, True),
        ('02 · MoE · declared compute and memory', 'workload', 'qwen3-moe-tp2-ep4-8ranks-declared-compute', True, False),
        ('03 · Flatfly · connectivity and topology study', 'preset', 'flatfly16', True, False),
        ('04 · CMesh · qualification refusal', 'preset', 'cmesh16', True, True),
        ('05 · SROTA · control and data planes', 'preset', 'srota32_plane_c', True, False),
        ('06 · Explicit graph · draft-only empty states', 'preset', 'explicit16', False, False),
        ('07 · Torus · wraparound and revision history', 'preset', 'torus25', True, False),
        ('08 · CMesh c=3 · compile refusal', 'preset', 'cmesh16', True, False),
        # Never compiled: the only fixture that promises zero runs, so the empty
        # analysis sections stay exercised even if another fixture gets evaluated.
        ('09 · Explicit graph · never evaluated', 'preset', 'explicit16', False, False),
    ]
    records = []
    for name, kind, source, compile_now, evaluate in scenarios:
        full_name = 'Flow test ' + name
        if full_name in existing:
            records.append({'name': full_name, 'project_id': existing[full_name]['project']['project_id'], 'reused': True})
            continue
        detail = api('/projects', {'name': full_name, 'workload_id': source}) if kind == 'workload' else api('/projects/from-preset', {'name': full_name, 'preset_id': source})
        pid = detail['project']['project_id']
        if source == 'qwen3-moe-tp2-ep4-8ranks-declared-compute':
            draft = api(f'/projects/{pid}/draft')
            request = draft['request']
            controllers = sum(agent['count'] for agent in request['agents'] if agent['kind'] == 'hbm_controller')
            for stage in request['compute']['stages']:
                for operand in ('input', 'weight', 'output'):
                    if stage.get(operand + '_bytes', 0) > 0:
                        # Explicit synthetic test policy, not inferred model placement.
                        stage[operand + '_loc'] = f"LOCAL:{stage['owner'] % controllers}"
            if 'c=3' in name:
                # Out-of-envelope concentration: 3 seats x radix 2 cannot seat 16
                # agents, so the compiler must refuse instead of approximating.
                request['noc_config']['concentration'] = 3
            api(f'/projects/{pid}/draft', {'request': request, 'expected_draft_design_hash': draft['design_hash']}, method='PUT')
        if source == 'cmesh16':
            # The catalog preset is frozen v2; use explicit v3 traffic facts.
            draft = api(f'/projects/{pid}/draft')
            example = Path(__file__).resolve().parents[1] / 'tracks/t3-topology/examples/dense_4b_32tiles_conc4-v3.json'
            request = json.loads(example.read_text())
            request.pop('design_hash', None)
            request.pop('guardrail_hash', None)
            if 'c=3' in name:
                # Out-of-envelope concentration: 3 seats x radix 2 cannot seat 16
                # agents, so the compiler must refuse instead of approximating.
                request['noc_config']['concentration'] = 3
            api(f'/projects/{pid}/draft', {'request': request, 'expected_draft_design_hash': draft['design_hash']}, method='PUT')
        record = {'name': full_name, 'project_id': pid, 'source': source}
        records.append(record)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(records, indent=2))
        try:
            if compile_now:
                draft = api(f'/projects/{pid}/draft')
                compiled = api(f'/projects/{pid}/compile', {'expected_draft_design_hash': draft['design_hash']})
                record['compilation'] = compiled
                rid = compiled.get('revision_id')
                if rid:
                    record['evaluation_plan'] = api(f'/revisions/{rid}/evaluation-plan')
                    if evaluate:
                        record['evaluation_job'] = api(f'/revisions/{rid}/evaluate', {'questions': ['NETWORK_COMPLETION']})
        except Exception as error:
            record['error'] = str(error)
        OUTPUT.write_text(json.dumps(records, indent=2))
        print(full_name, pid, record.get('error', record.get('compilation', {}).get('compilation', {}).get('status', 'draft only')), flush=True)
    OUTPUT.write_text(json.dumps(records, indent=2))
    print('Evidence:', OUTPUT)


if __name__ == '__main__':
    main()
