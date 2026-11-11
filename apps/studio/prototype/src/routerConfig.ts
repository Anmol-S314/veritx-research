// Router facts come from the compiled revision, never from a local default.
// The engine carries ONE RouterBehaviorArtifact for the fabric, so these are
// router-class facts: selecting a different router must not invent a different
// configuration.
import type { CompileResult } from './gateway';

export type RouterFact = { label: string; value: string; mono?: boolean };

const flits = (value: number): string => `${value} flit${value === 1 ? '' : 's'}`;

export function routerConfiguration(result: CompileResult | null): RouterFact[] {
  const resources = result?.groups?.resources;
  if (!resources) return [];
  const arbitration = resources.arbitration ?? {};
  const facts: RouterFact[] = [];
  if (resources.vc_count !== undefined) facts.push({ label: 'Virtual channels', value: `${resources.vc_count} per port` });
  if (arbitration.input_buffer_depth_flits_per_vc !== undefined) facts.push({ label: 'Input buffer', value: `${flits(arbitration.input_buffer_depth_flits_per_vc)} / VC` });
  if (arbitration.output_stage_depth_flits_per_vc !== undefined) facts.push({ label: 'Output stage', value: `${flits(arbitration.output_stage_depth_flits_per_vc)} / VC` });
  if (arbitration.flow_control) facts.push({ label: 'Flow control', value: arbitration.flow_control });
  if (arbitration.vc_allocator) facts.push({ label: 'VC allocator', value: arbitration.vc_allocator });
  if (arbitration.switch_allocator) facts.push({ label: 'Switch allocator', value: arbitration.switch_allocator });
  if (arbitration.allocator_iterations !== undefined) facts.push({ label: 'Allocator iterations', value: String(arbitration.allocator_iterations) });
  if (arbitration.input_vc_packet_policy) facts.push({ label: 'Input VC packet policy', value: arbitration.input_vc_packet_policy });
  if (resources.traffic_class_to_vcs?.length) {
    facts.push({ label: 'Traffic class → VC', value: resources.traffic_class_to_vcs.map(([cls, vcs]) => `${cls}: ${vcs.join(', ')}`).join(' · ') });
  }
  if (resources.vc_to_routing_class?.length) {
    facts.push({ label: 'VC → routing class', value: resources.vc_to_routing_class.map(([vc, cls]) => `${vc}: ${cls}`).join(' · ') });
  }
  return facts;
}

export function deadlockFacts(result: CompileResult | null): RouterFact[] {
  const deadlock = result?.groups?.resources?.deadlock;
  if (!deadlock) return [];
  const witness = deadlock.witness ?? {};
  const evidence = deadlock.evidence ?? {};
  const evidenceNodes = typeof evidence.nodes === 'number' ? evidence.nodes : undefined;
  const evidenceEdges = typeof evidence.edges === 'number' ? evidence.edges : undefined;
  const evidenceCycle = Array.isArray(evidence.cycle) ? evidence.cycle.length : undefined;
  const cycle = witness.acyclic === true || witness.acyclic === false
    ? (witness.acyclic ? 'none' : 'found')
    : evidenceCycle !== undefined ? (evidenceCycle ? 'found' : 'none') : undefined;
  const nodeCount = witness.node_count ?? evidenceNodes;
  const edgeCount = witness.edge_count ?? evidenceEdges;
  const facts: RouterFact[] = [];
  if (deadlock.status) facts.push({ label: 'Status', value: deadlock.status });
  if (deadlock.method) facts.push({ label: 'Method', value: deadlock.method });
  if (typeof evidence.proof_method === 'string') facts.push({ label: 'Proof method', value: evidence.proof_method });
  if (cycle) facts.push({ label: 'Cycle', value: cycle });
  if (witness.sccs_gt_1 !== undefined && witness.sccs_gt_1 !== null) facts.push({ label: 'SCCs > 1', value: String(witness.sccs_gt_1) });
  if (nodeCount !== undefined) facts.push({ label: 'CDG nodes', value: String(nodeCount) });
  if (edgeCount !== undefined) facts.push({ label: 'CDG edges', value: String(edgeCount) });
  if (witness.vc_count !== undefined && witness.vc_count !== null) facts.push({ label: 'VCs in proof', value: String(witness.vc_count) });
  if (witness.escape_vcs) facts.push({ label: 'Escape VCs', value: witness.escape_vcs.length ? witness.escape_vcs.join(', ') : 'none' });
  if (witness.cdg_route_classes?.length) facts.push({ label: 'Proof route classes', value: witness.cdg_route_classes.join(', ') });
  if (witness.route_realization_scheme) facts.push({ label: 'Route realization', value: witness.route_realization_scheme });
  return facts;
}
