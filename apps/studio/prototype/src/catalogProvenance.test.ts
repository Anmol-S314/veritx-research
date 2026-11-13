import { describe, expect, it } from 'vitest';
import { configSummary, rtlVerdict } from './CatalogCampaign';
import type { CatalogRow } from './gateway';

const row = (overrides: Partial<CatalogRow>): CatalogRow => ({
  topology_id: 'mesh', label: 'Mesh', topology: {}, reason: null,
  attempt: 1, status: 'EVALUATED', analyses: [], objective_values: {},
  ...overrides,
});

describe('catalog selection provenance', () => {
  it('never renders a missing RTL verdict as support', () => {
    const verdict = rtlVerdict(null);
    expect(verdict.tone).toBe('amber');
    expect(verdict.text).toContain('not recorded');
    expect(verdict.detail).toContain('Run the catalog again');
  });

  it('distinguishes the certified 2-VC slice from the 1-VC emitter case', () => {
    const certified = rtlVerdict({
      supported: true, code: 'SUPPORTED_CERTIFIED_2VC', reason: null,
      vc_count: 2, emitted_vcs: 2, matches_certified_vc_count: true,
      shared_wire_links: 0, router_count: 36,
    });
    const single = rtlVerdict({
      supported: true, code: 'SUPPORTED_SINGLE_CLASS', reason: null,
      vc_count: 1, emitted_vcs: 2, matches_certified_vc_count: false,
      shared_wire_links: 0, router_count: 36,
    });
    expect(certified.tone).toBe('amber');
    expect(certified.text).toContain('Preview · 2 VCs');
    expect(single.tone).toBe('amber');
    expect(single.text).toContain('Preview · 2 VCs (measured 1)');
    // Both are preview support, never a final-RTL claim.
    expect(certified.detail).toContain('not final RTL');
    expect(single.detail).toContain('VC scheme is not equivalent');
  });

  it('carries the backend reason for an unsupported fabric', () => {
    const verdict = rtlVerdict({
      supported: false, code: 'UNSUPPORTED_VC_SCHEME',
      reason: 'The selected gec_mecs fabric needs 5 VCs; no matching RTL emitter exists.',
      vc_count: 5, emitted_vcs: 2, matches_certified_vc_count: false,
      shared_wire_links: 0, router_count: 36,
    });
    expect(verdict.tone).toBe('red');
    expect(verdict.text).toContain('No RTL preview');
    expect(verdict.detail).toContain('5 VCs');
  });

  it('shows the buffer depth and routing law that produced the number', () => {
    expect(configSummary(row({
      config: { controls_id: 'sha256:x', input_buffer_depth_flits_per_vc: 8, link_width: 64, arbitration: null, matched: true },
      fabric: { router_count: 36, shared_wire_links: 0, routing_class: 'DOR_XY', vc_count: 2 },
    }))).toBe('8 flits/VC · DOR_XY');
    expect(configSummary(row({
      config: { controls_id: 'sha256:x', input_buffer_depth_flits_per_vc: null, link_width: 64, arbitration: null, matched: true },
      fabric: { router_count: 36, shared_wire_links: 0, routing_class: null, vc_count: 2 },
    }))).toBe('buffer: default · routing not recorded');
  });

  it('says a configuration was not recorded instead of implying it was matched', () => {
    expect(configSummary(row({ config: null, fabric: null }))).toBe('buffer: default · routing not recorded');
  });
});
