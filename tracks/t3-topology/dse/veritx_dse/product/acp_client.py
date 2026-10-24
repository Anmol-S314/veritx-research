"""Bounded ACP-v1 stdio text client. No filesystem/terminal/MCP capabilities.

The configured process is owner-trusted, NOT sandboxed by this protocol client.
"""
from __future__ import annotations

import json
import os
import selectors
import select
import signal
import subprocess
import tempfile
import time
from pathlib import Path

class ACPError(ValueError):
    pass

def command():
    if os.environ.get('VERITX_ACP_TRUST_PROCESS') != '1':
        raise ACPError('ACP requires owner approval: VERITX_ACP_TRUST_PROCESS=1. The process is not OS-sandboxed.')
    try:
        value = json.loads(os.environ.get('VERITX_ACP_COMMAND', 'null'))
    except ValueError:
        raise ACPError('VERITX_ACP_COMMAND must be a JSON argv array.') from None
    if (not isinstance(value, list) or not value or len(value) > 32
            or any(not isinstance(x, str) or not x or len(x) > 4096 for x in value)
            or not Path(value[0]).is_absolute() or not Path(value[0]).is_file()
            or not os.access(value[0], os.X_OK)):
        raise ACPError('ACP requires a fixed absolute executable and bounded JSON argv.')
    return value

def capability():
    try:
        command()
        return {'configured': True, 'reason': None}
    except ACPError as exc:
        return {'configured': False, 'reason': str(exc)}

def complete(text: str, timeout: float = 30) -> str:
    argv = command()
    if len(text.encode()) > 128 * 1024:
        raise ACPError('ACP prompt exceeds 128 KiB.')
    env = {name: os.environ[name] for name in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME') if name in os.environ}
    try:
        allowed = json.loads(os.environ.get('VERITX_ACP_ENV_ALLOW', '[]'))
        if not isinstance(allowed, list) or len(allowed) > 32 or any(not isinstance(k, str) or not k.isidentifier() for k in allowed):
            raise ValueError()
    except ValueError:
        raise ACPError('VERITX_ACP_ENV_ALLOW must list at most 32 environment names.') from None
    env.update({name: os.environ[name] for name in allowed if name in os.environ})
    with tempfile.TemporaryDirectory(prefix='veritx-acp-') as cwd:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=cwd, env=env,
                                   start_new_session=True, bufsize=0)
        os.set_blocking(process.stdin.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        pending = bytearray(); total = 0; chunks = []; serial = 0
        deadline = time.monotonic() + timeout
        def send(value):
            try:
                payload = memoryview(json.dumps(value, separators=(',', ':')).encode() + b'\n')
                while payload:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([], [process.stdin], [], remaining)[1]:
                        raise ACPError('ACP input timed out.')
                    try:
                        count = os.write(process.stdin.fileno(), payload)
                        payload = payload[count:]
                    except BlockingIOError:
                        continue
            except (OSError, BrokenPipeError):
                raise ACPError('ACP process closed its input.') from None
        def rpc(method, params):
            nonlocal serial, total
            serial += 1; request_id = serial
            send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
            while time.monotonic() < deadline:
                while b'\n' in pending:
                    line, _, rest = pending.partition(b'\n'); pending[:] = rest
                    if not line.strip():
                        continue
                    try:
                        message = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise ACPError('ACP emitted invalid JSON-RPC framing.') from None
                    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                        raise ACPError('ACP emitted an invalid JSON-RPC envelope.')
                    if message.get('method'):
                        params = message.get('params') or {}
                        if not isinstance(params, dict):
                            raise ACPError('ACP emitted invalid method parameters.')
                        if 'id' in message:
                            if message['method'] == 'session/request_permission':
                                options = params.get('options', [])
                                if not isinstance(options, list) or any(not isinstance(o, dict) for o in options):
                                    raise ACPError('ACP emitted invalid permission options.')
                                reject = next((o for o in options if o.get('kind') == 'reject_once'), None)
                                outcome = {'outcome': 'selected', 'optionId': reject['optionId']} if reject else {'outcome': 'cancelled'}
                                send({'jsonrpc': '2.0', 'id': message['id'], 'result': {'outcome': outcome}})
                            else:
                                send({'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601, 'message': 'Client capability unavailable'}})
                        elif message['method'] == 'session/update':
                            update = params.get('update', {})
                            if not isinstance(update, dict):
                                raise ACPError('ACP emitted an invalid session update.')
                            if update.get('sessionUpdate') in ('tool_call', 'tool_call_update'):
                                raise ACPError('ACP runtime attempted tool activity in text-only mode.')
                            content = update.get('content') or {}
                            if not isinstance(content, dict):
                                raise ACPError('ACP emitted invalid content.')
                            if update.get('sessionUpdate') == 'agent_message_chunk' and content.get('type') == 'text':
                                part = content.get('text')
                                if not isinstance(part, str):
                                    raise ACPError('ACP emitted invalid text content.')
                                chunks.append(part)
                        continue
                    if message.get('id') == request_id:
                        if 'error' in message:
                            raise ACPError(f'ACP refused {method}; check runtime authentication and capabilities.')
                        result = message.get('result') or {}
                        if not isinstance(result, dict):
                            raise ACPError('ACP emitted an invalid method result.')
                        return result
                ready = selector.select(max(0, min(0.25, deadline - time.monotonic())))
                for key, _ in ready:
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        if key.data == 'stdout':
                            raise ACPError('ACP process exited before completing the request.')
                        continue
                    total += len(data)
                    if total > 256 * 1024:
                        raise ACPError('ACP protocol output exceeds 256 KiB.')
                    if key.data == 'stdout':
                        pending.extend(data)
            raise ACPError('ACP request timed out.')
        try:
            initialized = rpc('initialize', {'protocolVersion': 1, 'clientCapabilities': {'fs': {'readTextFile': False, 'writeTextFile': False}, 'terminal': False}, 'clientInfo': {'name': 'srota-studio', 'version': '0.1.0'}})
            if initialized.get('protocolVersion') != 1:
                raise ACPError('ACP protocol version 1 is required.')
            session = rpc('session/new', {'cwd': cwd, 'mcpServers': []})
            session_id = session.get('sessionId')
            if not isinstance(session_id, str) or not session_id:
                raise ACPError('ACP returned no session ID.')
            result = rpc('session/prompt', {'sessionId': session_id, 'prompt': [{'type': 'text', 'text': text}]})
            if result.get('stopReason') != 'end_turn':
                raise ACPError('ACP turn did not complete normally.')
            output = ''.join(chunks)
            if not output or len(output.encode()) > 64 * 1024:
                raise ACPError('ACP returned empty or oversized text.')
            return output
        finally:
            selector.close()
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=1)
                except ProcessLookupError:
                    pass
