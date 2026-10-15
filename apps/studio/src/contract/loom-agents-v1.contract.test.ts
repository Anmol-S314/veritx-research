import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject, type LoomProject } from '../graph/project';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

const sample = (): LoomProject => ({
  ...buildPreset('ring-8'),
  agents: [{
    id: 'cpu0', nodeId: 'n1', role: 'initiator', protocol: 'AXI4', capabilities: ['read', 'write'],
    ports: [{
      id: 'm_axi', role: 'initiator', protocol: 'AXI4', dataWidth: 256, addressWidth: 48,
      capabilities: ['read', 'write'], addressWindows: [{ base: '0x80000000', size: '0x10000', permissions: ['read', 'write'] }],
    }],
  }],
});

describe('agent and port project v1 contract', () => {
  it('serializes role, protocol, widths, capabilities and address windows', () => {
    const p = sample();
    expect(validateProject(p)).toEqual([]);
    expect(parseProject(serializeProject(p)).agents).toEqual(p.agents);
    expect(SCHEMA.$defs.agent.required).toEqual(['id', 'nodeId', 'role', 'protocol', 'capabilities', 'ports']);
    expect(SCHEMA.$defs.agentRole.enum).toEqual(['initiator', 'target', 'bidirectional']);
    expect(SCHEMA.$defs.agentPort.properties.dataWidth.minimum).toBe(1);
    expect(SCHEMA.$defs.addressWindow.properties.base.pattern).toContain('0x');
  });
  it('bounds address-window numbers and enforces the declared address width', () => {
    const tooWide = sample();
    tooWide.agents![0]!.ports[0]!.addressWindows![0] = { base: '0xffffffffffff', size: '0x2', permissions: ['read'] };
    expect(validateProject(tooWide).map(e => e.path)).toContain('$.agents[0].ports[0].addressWindows[0].size');
    const oversized = sample();
    oversized.agents![0]!.ports[0]!.addressWindows![0]!.size = `0x${'f'.repeat(10000)}`;
    expect(() => validateProject(oversized)).not.toThrow();
    expect(validateProject(oversized).map(e => e.path)).toContain('$.agents[0].ports[0].addressWindows[0].size');
    expect(SCHEMA.$defs.addressWindow.properties.base.maxLength).toBe(18);
    expect(SCHEMA.$defs.addressWindow.properties.size.maxLength).toBe(19);
  });

  it('reports exact overlapping target address windows and permits adjacent windows', () => {
    const p = sample();
    p.agents = [
      { id: 'mem0', nodeId: 'n1', role: 'target', protocol: 'AXI4', capabilities: ['read'], ports: [
        { id: 'target0', role: 'target', protocol: 'AXI4', dataWidth: 256, addressWidth: 48, capabilities: ['read'], addressWindows: [{ base: '0x80000000', size: '0x10000', permissions: ['read'] }] },
      ] },
      { id: 'mem1', nodeId: 'n2', role: 'target', protocol: 'AXI4', capabilities: ['read'], ports: [
        { id: 'target1', role: 'target', protocol: 'AXI4', dataWidth: 256, addressWidth: 48, capabilities: ['read'], addressWindows: [{ base: '0x80000080', size: '0x10000', permissions: ['read'] }] },
      ] },
    ];
    const issues = validateProject(p);
    expect(issues.some(issue => issue.severity === 'error' && issue.message.includes('mem0/target0 0x80000000..0x8000ffff overlaps mem1/target1 0x80000080..0x8001007f'))).toBe(true);
    p.agents[1]!.ports[0]!.addressWindows![0]!.base = '0x80010000';
    expect(validateProject(p).filter(issue => issue.message.includes('overlaps'))).toEqual([]);
  });

  it('rejects dangling nodes, duplicate agent/port IDs, invalid roles/widths and unsafe address strings', () => {
    const p = sample();
    p.agents![0]!.nodeId = 'not-a-node';
    p.agents![0]!.ports[0]!.role = 'router' as 'initiator';
    p.agents![0]!.ports[0]!.dataWidth = 0;
    p.agents![0]!.ports[0]!.addressWindows![0]!.base = '../escape';
    p.agents![0]!.capabilities.push('read');
    p.agents![0]!.ports[0]!.capabilities.push('write');
    p.agents![0]!.ports[0]!.addressWindows![0]!.permissions.push('read');
    (p.agents![0] as unknown as Record<string, unknown>).viewData = {};
    (p.agents![0]!.ports[0] as unknown as Record<string, unknown>).displayName = 'AXI';
    expect(validateProject(p).map(e => e.path)).toEqual(expect.arrayContaining([
      '$.agents[0].nodeId', '$.agents[0].ports[0].role', '$.agents[0].ports[0].dataWidth', '$.agents[0].ports[0].addressWindows[0].base',
      '$.agents[0].capabilities', '$.agents[0].ports[0].capabilities', '$.agents[0].ports[0].addressWindows[0].permissions', '$.agents[0].viewData', '$.agents[0].ports[0].displayName',
    ]));
  });
});
