import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { api } from '../api';
import type { CompileResultView, RevisionView } from '../api/types';
import { parseRoute } from '../router';

vi.mock('../components/CompileResult/CompileSummary', () => ({ default: () => null }));
vi.mock('../components/CompileResult/MappingInspector', () => ({ default: () => null }));
vi.mock('../components/CompileResult/FabricInspector', () => ({ default: () => null }));
vi.mock('../components/CompileResult/RoutingInspector', () => ({ default: () => null }));
vi.mock('../components/CompileResult/ResourceInspector', () => ({ default: () => null }));
vi.mock('../components/CompileResult/AddressDecodeInspector', () => ({ default: () => null }));
vi.mock('../components/CompileResult/ProvenanceInspector', () => ({ default: () => null }));
vi.mock('../components/CompileResult/BackendAvailability', () => ({ default: () => null }));
vi.mock('../components/CompileResult/ExecutionReadiness', () => ({
  default: () => null,
  CapabilityConsequences: () => null,
}));
vi.mock('../components/CompileResult/EngineeringFindings', () => ({ default: () => null }));
vi.mock('../components/CompileResult/RevisionDiff', () => ({ RevisionDiffBody: () => null }));
vi.mock('../components/CompileResult/VerifyInspector', () => ({ default: () => null }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

const revision = {
  revision_id: 'rev-1',
  project_id: 'project-1',
  display_name: 'Pinned revision',
} as unknown as RevisionView;

function compileResult(groups: Record<string, unknown> = {
  summary: { derived: { routers: 4, channels: 8, endpoints: 4 } },
  mapping: {},
  fabric: {},
  routing: {},
  resources: {},
  address_decode: {},
  provenance: {},
}): CompileResultView {
  return {
    contract_version: 1,
    available: true,
    revision_id: 'rev-1',
    group_order: ['summary', 'mapping', 'fabric', 'routing', 'resources',
      'address_decode', 'provenance'],
    groups,
  } as unknown as CompileResultView;
}

function mockApi(result = compileResult()): void {
  vi.spyOn(api, 'health').mockResolvedValue({} as never);
  vi.spyOn(api, 'listProjects').mockResolvedValue({
    contract_version: 1, projects: [],
  } as never);
  vi.spyOn(api, 'revision').mockResolvedValue(revision);
  vi.spyOn(api, 'compileResult').mockResolvedValue(result);
  vi.spyOn(api, 'preflight').mockResolvedValue({} as never);
  vi.spyOn(api, 'revisionDiff').mockResolvedValue({} as never);
}

function open(path: string): void {
  window.history.replaceState({}, '', path);
  render(<App />);
}

describe('revision compile-result deep links', () => {
  beforeEach(() => mockApi());

  it('parses and renders a direct address-decode link, updates selection URLs, and restores back/forward', async () => {
    expect(parseRoute('/revisions/rev-1/address-decode')).toEqual({
      kind: 'revision', revisionId: 'rev-1', group: 'address_decode',
    });

    open('/revisions/rev-1/address-decode');
    const addressDecode = await screen.findByRole('button', { name: 'Address decode' });
    expect(addressDecode.getAttribute('aria-current')).toBe('true');
    expect(api.revision).toHaveBeenCalledWith('rev-1');
    expect(api.compileResult).toHaveBeenCalledWith('rev-1');
    expect(screen.getByRole('link', { name: 'Compile console' }).getAttribute('href'))
      .toBe('/projects/project-1/compile');

    fireEvent.click(screen.getByRole('button', { name: 'Mapping' }));
    await waitFor(() => expect(window.location.pathname).toBe('/revisions/rev-1/mapping'));
    expect(screen.getByRole('button', { name: 'Mapping' }).getAttribute('aria-current'))
      .toBe('true');

    window.history.back();
    await waitFor(() => expect(window.location.pathname)
      .toBe('/revisions/rev-1/address-decode'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Address decode' })
      .getAttribute('aria-current')).toBe('true'));

    window.history.forward();
    await waitFor(() => expect(window.location.pathname).toBe('/revisions/rev-1/mapping'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mapping' })
      .getAttribute('aria-current')).toBe('true'));
  });

  it('deep-links the optional control-plane inspector when present', async () => {
    const result = compileResult();
    vi.mocked(api.compileResult).mockResolvedValue({
      ...result,
      group_order: [...(result.group_order ?? []), 'control_plane'],
      groups: {
        ...result.groups,
        control_plane: {
          declared: false,
          scope: 'DECLARED_STRUCTURE_ONLY',
          reason: 'No control-plane subnet was declared.',
        },
      },
    } as unknown as CompileResultView);
    expect(parseRoute('/revisions/rev-1/control-plane')).toEqual({
      kind: 'revision', revisionId: 'rev-1', group: 'control_plane',
    });

    open('/revisions/rev-1/control-plane');
    expect(await screen.findByText('No control-plane subnet was declared.'))
      .toBeTruthy();
    expect(screen.getByRole('button', { name: 'Control plane' })
      .getAttribute('aria-current')).toBe('true');
  });

  it('shows an explicit unavailable state when an older revision lacks a known group', async () => {
    vi.mocked(api.compileResult).mockResolvedValue(compileResult({
      summary: { derived: { routers: 4, channels: 8, endpoints: 4 } },
    }));
    open('/revisions/rev-1/mapping');

    expect(await screen.findByText(
      'This revision does not include this inspector group.',
    )).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Mapping' }).getAttribute('aria-current'))
      .toBe('true');
  });

  it('refuses an unknown group instead of loading Summary or Overview', async () => {
    open('/revisions/rev-1/energy');

    expect(await screen.findByText('Not found: /revisions/rev-1/energy')).toBeTruthy();
    expect(api.revision).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Summary' })).toBeNull();
  });
});
