import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject } from '../graph/project';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

describe('clock/reset/power domain v1 contract', () => {
  const project = () => {
    const base = buildPreset('ring-8');
    return {
      ...base,
      nodes: base.nodes.map(n => ({ ...n, clock: 'clk_fast', resetDomain: 'rst_n', powerDomain: 'pd_core' })),
      edges: base.edges.map((e, i) => i === 0 ? { ...e, domainCrossing: { clock: { policy: 'async_fifo' as const, elementNodeId: 'n1' }, reset: { policy: 'reset_bridge' as const }, power: { policy: 'isolation' as const } } } : e),
      domains: {
        clocks: [{ id: 'clk_fast', frequencyHz: 100000000, source: 'pll0' }],
        resets: [{ id: 'rst_n', polarity: 'active_low' as const, asynchronous: true, clockDomainId: 'clk_fast' }],
        powers: [{ id: 'pd_core', nominalVoltageV: 0.8, canPowerOff: true }],
        portAssignments: [{ nodeId: 'n1', portId: 'p_req', clockDomainId: 'clk_fast', resetDomainId: 'rst_n', powerDomainId: 'pd_core' }],
      },
    };
  };
  it('serializes node and port assignments plus explicit crossing policies', () => {
    const p = project();
    expect(validateProject(p)).toEqual([]);
    const roundTrip = parseProject(serializeProject(p));
    expect(roundTrip.domains).toEqual(p.domains);
    expect(roundTrip.edges[0].domainCrossing).toEqual(p.edges[0].domainCrossing);
    expect(SCHEMA.$defs.domains.required).toEqual(['clocks', 'resets', 'powers', 'portAssignments']);
    expect(SCHEMA.$defs.portDomainAssignment.properties).toHaveProperty('resetDomainId');
    expect(SCHEMA.$defs.domainCrossing.properties).toHaveProperty('clock');
    expect(SCHEMA.$defs.domainCrossing.properties).toHaveProperty('power');
  });
  it('rejects malformed nested domain values and duplicate port assignments', () => {
    const p = project();
    p.domains.clocks[0]!.frequencyHz = 0;
    p.domains.resets[0]!.polarity = 'active_middle' as 'active_low';
    p.domains.powers[0]!.canPowerOff = 'sometimes' as unknown as boolean;
    p.domains.portAssignments.push({ ...p.domains.portAssignments[0]! });
    (p.domains.portAssignments[0] as Record<string, unknown>).viewOnly = true;
    const crossing = p.edges[0].domainCrossing as unknown as { clock: Record<string, unknown> };
    crossing.clock.notes = 42;
    const paths = validateProject(p).map(issue => issue.path);
    expect(paths).toEqual(expect.arrayContaining([
      '$.domains.clocks[0].frequencyHz', '$.domains.resets[0].polarity', '$.domains.powers[0].canPowerOff',
      '$.domains.portAssignments[1]', '$.domains.portAssignments[0].viewOnly', '$.edges[0].domainCrossing.clock.notes',
    ]));
  });

  it('resolves stable port assignments against declared agent ports when available', () => {
    const p = project();
    const withAgent = {
      ...p,
      agents: [{ id: 'cpu0', nodeId: 'n1', role: 'initiator', protocol: 'AXI4', capabilities: [], ports: [{ id: 'p_req', role: 'initiator', protocol: 'AXI4', dataWidth: 64, capabilities: [] }] }],
    };
    withAgent.domains.portAssignments[0]!.portId = 'not-a-port';
    expect(validateProject(withAgent).map(issue => issue.path)).toContain('$.domains.portAssignments[0].portId');
  });

  it('reports dangling node/port domain references and invalid crossing elements', () => {
    const p = project();
    p.nodes[0].clock = 'missing-clock';
    p.domains.portAssignments[0].nodeId = 'not-a-node';
    const crossing = p.edges[0].domainCrossing as { clock: { elementNodeId: string } };
    crossing.clock.elementNodeId = 'not-a-node';
    expect(validateProject(p).map(e => e.path)).toEqual(expect.arrayContaining([
      '$.nodes[0].clock', '$.domains.portAssignments[0].nodeId', '$.edges[0].domainCrossing.clock.elementNodeId',
    ]));
  });
});
