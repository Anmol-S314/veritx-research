import { describe, expect, it } from 'vitest';
import SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

describe('project.json v1 schema surface', () => {
  it('is versioned and requires graph identity/version fields', () => {
    expect(SCHEMA.$schema).toBe('https://json-schema.org/draft/2020-12/schema');
    expect(SCHEMA.$id).toMatch(/\/v1\/project\.schema\.json$/);
    expect(SCHEMA.required).toEqual(expect.arrayContaining(['schemaVersion', 'compilerSemanticsVersion', 'presetHint', 'nodes', 'edges']));
    expect(SCHEMA.properties.schemaVersion.const).toBe(1);
    expect(SCHEMA.properties.compilerSemanticsVersion.const).toBe(1);
    expect(SCHEMA.additionalProperties).toBe(false);
  });

  it('covers every M0-01 typed project section and important referenced definitions', () => {
    expect(Object.keys(SCHEMA.properties)).toEqual(expect.arrayContaining([
      'nodes', 'edges', 'firewall', 'workload', 'vcConfig', 'domains', 'agents', 'floorplan', 'metadata', 'access',
    ]));
    expect(Object.keys(SCHEMA.$defs)).toEqual(expect.arrayContaining([
      'node', 'edge', 'catalogReference', 'agent', 'agentPort', 'domains', 'clockDomain', 'resetDomain',
      'powerDomain', 'portDomainAssignment', 'vcConfig', 'virtualChannel', 'trafficClassMap', 'arbitration',
      'workload', 'workloadPhase', 'communicationOp', 'timingHints', 'accessControl', 'firewallRule',
      'floorplan', 'physicalEdge', 'projectMetadata',
    ]));
    expect(SCHEMA.$defs.node.properties.catalogRef.$ref).toBe('#/$defs/catalogReference');
    expect(SCHEMA.$defs.edge.properties.pipelineStages.minimum).toBe(1);
    expect(SCHEMA.$defs.projectMetadata.additionalProperties).toBe(false);
  });
});
