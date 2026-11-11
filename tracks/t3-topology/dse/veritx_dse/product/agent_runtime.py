"""Optional text/translation broker. Models have no domain-operation tools."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from veritx_dse.optimization.ai_search import (
    ProviderError, provider_config, provider_headers, provider_open,
)
from veritx_dse.product import acp_client

MAX_PROMPT = 128 * 1024
MAX_RESPONSE = 256 * 1024

def transport():
    value = os.environ.get('VERITX_AGENT_TRANSPORT', 'openai')
    if value not in ('openai', 'acp'):
        raise ProviderError('VERITX_AGENT_TRANSPORT must be openai or acp.')
    return value

def capabilities():
    base_url = None
    try:
        mode = transport()
        if mode == 'acp':
            configured = acp_client.capability()
            ready, reason, model = configured['configured'], configured['reason'], None
        else:
            endpoint, model, _ = provider_config()
            base_url = endpoint.removesuffix('/chat/completions')
            ready, reason = True, None
    except ProviderError as exc:
        mode, ready, reason, model = os.environ.get('VERITX_AGENT_TRANSPORT', 'openai'), False, str(exc), None
    return {'contract_version': 1, 'configured': ready, 'transport': mode,
            'model': model, 'base_url': base_url, 'reason': reason, 'tools': [],
            'chat': True, 'workload_translation': True, 'timeout_s': 30,
            'max_context_bytes': MAX_PROMPT,
            'process_sandboxed': False if mode == 'acp' else None,
            'permission_policy': 'Client tool requests denied; adoption is a separate pinned human operation.'}

def complete_text(messages: list[dict], json_output: bool = False) -> str:
    if len(json.dumps(messages).encode()) > MAX_PROMPT:
        raise ProviderError('Agent context exceeds 128 KiB.')
    if transport() == 'acp':
        try:
            return acp_client.complete(json.dumps({'messages': messages}, ensure_ascii=False))
        except acp_client.ACPError as exc:
            raise ProviderError(str(exc)) from None
    endpoint, model, key = provider_config()
    body = {'model': model, 'messages': messages, 'max_tokens': 4096}
    if json_output:
        body['response_format'] = {'type': 'json_object'}
    encoded = json.dumps(body).encode()
    if len(encoded) > MAX_PROMPT:
        raise ProviderError('Agent request exceeds 128 KiB.')
    headers = provider_headers(key)
    try:
        with provider_open(
                lambda: urllib.request.Request(endpoint, data=encoded, headers=headers)) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ProviderError('Agent response exceeds 256 KiB.')
        content = json.loads(raw)['choices'][0]['message']['content']
    except urllib.error.HTTPError as exc:
        raise ProviderError(f'Agent provider HTTP {exc.code}; check server configuration.') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError('Agent provider connection failed.') from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise ProviderError('Agent provider returned an invalid response.') from None
    if not isinstance(content, str) or not content or len(content.encode()) > 64 * 1024:
        raise ProviderError('Agent response must be nonempty text below 64 KiB.')
    return content
