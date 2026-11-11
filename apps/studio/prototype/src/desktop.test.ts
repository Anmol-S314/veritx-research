import { afterEach, describe, expect, it, vi } from 'vitest';

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ invoke }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  invoke.mockReset();
});

describe('shared browser / desktop bootstrap', () => {
  it('leaves the ordinary browser gateway unchanged', async () => {
    vi.stubGlobal('window', {});
    const desktop = await import('./desktop');
    await desktop.initializeDesktop();
    expect(desktop.desktopGatewayBase).toBeUndefined();
    expect(invoke).not.toHaveBeenCalled();
  });

  it('uses the sidecar address for requests, streams and downloads', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} });
    const base = 'http://127.0.0.1:43123/launch-secret/gw';
    invoke.mockResolvedValue({ base });
    const desktop = await import('./desktop');
    await desktop.initializeDesktop();
    const fetch = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ status: 'ok' }),
    });
    vi.stubGlobal('fetch', fetch);
    const { gateway } = await import('./gateway');
    await gateway.health();
    expect(invoke).toHaveBeenCalledWith('gateway_connection');
    expect(fetch.mock.calls[0][0]).toBe(base + '/api/v1/health');
    expect(gateway.jobEventsUrl('job')).toBe(base + '/api/v1/jobs/job/events');
    expect(gateway.artifactUrl('run', 'result.json')).toBe(base + '/api/v1/runs/run/artifact?path=result.json');
  });

  it('does not silently fall back to fixtures when desktop startup fails', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} });
    invoke.mockRejectedValue(new Error('backend failed'));
    const desktop = await import('./desktop');
    await expect(desktop.initializeDesktop()).rejects.toThrow('backend failed');
    expect(desktop.desktopGatewayBase).toBeUndefined();
  });

  it('refuses a non-loopback backend address', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} });
    invoke.mockResolvedValue({ base: 'https://example.com/gw' });
    const desktop = await import('./desktop');
    await expect(desktop.initializeDesktop()).rejects.toThrow('invalid local address');
  });
});
