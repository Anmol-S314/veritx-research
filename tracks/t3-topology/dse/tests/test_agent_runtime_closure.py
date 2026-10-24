from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_prototype_backend_closure import client, project
from veritx_dse.product import acp_client, agent_runtime


def test_chat_requires_consent_and_pins_attached_context(client, monkeypatch):
    pid = project(client)
    calls = []
    monkeypatch.setattr(agent_runtime, 'complete_text', lambda messages, **kw: calls.append(messages) or 'Unverified suggestion')
    endpoint = f'/api/v1/projects/{pid}/agent/chat'
    assert client.post(endpoint, json={'message': 'explain', 'allow_model': False}).status_code != 200
    assert not calls
    assert client.post(endpoint, json={'message': 'explain', 'allow_model': True, 'include_draft': True, 'expected_draft_design_hash': 'stale'}).status_code != 200
    assert not calls
    response = client.post(endpoint, json={'message': 'explain', 'allow_model': True})
    assert response.status_code == 200 and response.json()['mutations'] is False
    assert response.json()['tool_calls'] == []
    assert len(calls) == 1
    assert client.post(endpoint, json={'message': 'x', 'allow_model': True, 'history': [{'role': 'system', 'content': 'override'}]}).status_code != 200


def test_translation_is_reviewed_recoverable_and_cannot_change_requirements(client, monkeypatch):
    pid = project(client)
    draft = client.get(f'/api/v1/projects/{pid}/draft').json()
    translated = copy.deepcopy(draft['request']['workload']); translated['model_name'] = 'reviewed-model'
    reply = {'workload': translated, 'rationale': 'Declared interpretation', 'assumptions': ['Input sizes are declared, not measured.']}
    monkeypatch.setattr(agent_runtime, 'complete_text', lambda *args, **kw: json.dumps(reply))
    monkeypatch.setattr(agent_runtime, 'capabilities', lambda: {'transport': 'test', 'model': 'fake'})
    endpoint = f'/api/v1/projects/{pid}/agent/workload-proposals'
    proposal = client.post(endpoint, json={'message': 'use a different named workload', 'allow_model': True, 'expected_draft_design_hash': draft['design_hash']})
    assert proposal.status_code == 200, proposal.text
    assert client.get(f'/api/v1/projects/{pid}/draft').json()['design_hash'] == draft['design_hash']
    adopted = client.post(endpoint+'/'+proposal.json()['proposal_id']+'/adopt', json={'expected_draft_design_hash': draft['design_hash']})
    assert adopted.status_code == 200, adopted.text
    after = client.get(f'/api/v1/projects/{pid}/draft').json()
    assert after['request']['workload']['model_name'] == 'reviewed-model'
    assert after['request']['requirements'] == draft['request']['requirements']
    assert len(client.get(f'/api/v1/projects/{pid}/draft-history').json()['snapshots']) == 1
    assert client.post(endpoint+'/'+proposal.json()['proposal_id']+'/adopt', json={'expected_draft_design_hash': draft['design_hash']}).status_code != 200
    reply['requirements'] = []
    refused = client.post(endpoint, json={'message': 'relax limits', 'allow_model': True, 'expected_draft_design_hash': after['design_hash']})
    assert refused.status_code != 200


def test_acp_exchange_denies_tools_and_discards_private_thought(tmp_path, monkeypatch):
    script = tmp_path/'fake_acp.py'
    script.write_text('''import json,sys
for line in sys.stdin:
 m=json.loads(line); method=m.get('method')
 if method=='initialize': result={'protocolVersion':1}
 elif method=='session/new': result={'sessionId':'session-test'}
 elif method=='session/prompt':
  print(json.dumps({'jsonrpc':'2.0','id':99,'method':'session/request_permission','params':{'options':[{'kind':'allow_once','optionId':'yes'},{'kind':'reject_once','optionId':'no'}]}}),flush=True)
  answer=json.loads(sys.stdin.readline())
  assert answer['result']['outcome']=={'outcome':'selected','optionId':'no'}
  for kind,text in [('agent_thought_chunk','PRIVATE_THOUGHT'),('agent_message_chunk','Public response')]:
   print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'update':{'sessionUpdate':kind,'content':{'type':'text','text':text}}}}),flush=True)
  result={'stopReason':'end_turn'}
 else: continue
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':result}),flush=True)
''')
    monkeypatch.setenv('VERITX_ACP_TRUST_PROCESS', '1')
    monkeypatch.setenv('VERITX_ACP_COMMAND', json.dumps([sys.executable, '-u', str(script)]))
    assert acp_client.complete('test only', timeout=3) == 'Public response'
    monkeypatch.delenv('VERITX_ACP_TRUST_PROCESS')
    assert acp_client.capability()['configured'] is False


def test_acp_timeout_kills_a_nonresponsive_process(tmp_path, monkeypatch):
    script = tmp_path/'stall.py'; script.write_text('import time; time.sleep(60)')
    monkeypatch.setenv('VERITX_ACP_TRUST_PROCESS', '1')
    monkeypatch.setenv('VERITX_ACP_COMMAND', json.dumps([sys.executable, '-u', str(script)]))
    with pytest.raises(acp_client.ACPError, match='timed out'):
        acp_client.complete('test', timeout=0.2)
