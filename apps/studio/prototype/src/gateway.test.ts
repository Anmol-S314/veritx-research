import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

it('shares simultaneous reads, but re-reads after completion', async () => {
  let resolve!: (response: Response) => void;
  const response = new Promise<Response>(done => { resolve = done; });
  const fetch = vi.fn(() => response);
  vi.stubGlobal('fetch', fetch);
  const { gateway } = await import('./gateway');
  const first = gateway.run('run-1'), second = gateway.run('run-1');
  const count = fetch.mock.calls.length;
  resolve({ ok: true, json: async () => ({ run_id: 'run-1' }) } as Response);
  await Promise.all([first, second]);
  expect(count).toBe(1);
  fetch.mockResolvedValueOnce(Response.json({ run_id: 'run-1', status: 'UPDATED' }));
  expect(await gateway.run('run-1')).toMatchObject({ status: 'UPDATED' });
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('evicts failed reads so retry reaches the server', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response('unavailable', { status: 503 }))
    .mockResolvedValueOnce(Response.json({ run_id: 'run-1' }));
  vi.stubGlobal('fetch', fetch);
  const { gateway } = await import('./gateway');
  await expect(gateway.run('run-1')).rejects.toMatchObject({ status: 503 });
  expect(await gateway.run('run-1')).toMatchObject({ run_id: 'run-1' });
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('does not share a pending read across a mutation', async () => {
  let resolveOld!: (response: Response) => void;
  const fetch = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { resolveOld = resolve; }))
    .mockResolvedValueOnce(Response.json({ project: { name: 'New name' } }))
    .mockResolvedValueOnce(Response.json({ project: { name: 'New name' } }));
  vi.stubGlobal('fetch', fetch);
  const { gateway } = await import('./gateway');
  const before = gateway.project('p-1');
  await gateway.renameProject('p-1', 'New name');
  const after = gateway.project('p-1');
  resolveOld(Response.json({ project: { name: 'Old name' } }));
  expect(await before).toMatchObject({ project: { name: 'Old name' } });
  expect(await after).toMatchObject({ project: { name: 'New name' } });
  expect(fetch).toHaveBeenCalledTimes(3);
});
