import { initialInputs, validInputs, type WorkingInputs } from './workload';

export const STORAGE_KEY = 'srota-stitch-prototype:v1';
export const BASE_REVISION = 'rev-captured-r5';
export const ROUTERS = Array.from({ length: 16 }, (_, i) => `R_${Math.floor(i / 4)}_${i % 4}`);
export const DOMAIN_IDS = ['clk_fabric', 'clk_memory', 'clk_host'] as const;
export type DomainId = typeof DOMAIN_IDS[number];
export const DOMAINS: { id: DomainId; mhz: number; description: string }[] = [
  { id: 'clk_fabric', mhz: 1400, description: 'Declared network model clock' },
  { id: 'clk_memory', mhz: 800, description: 'Declared memory-side interface clock' },
  { id: 'clk_host', mhz: 1000, description: 'Declared host-side interface clock' },
];
export type Endpoint = { id: string; role: 'Initiator' | 'Target' | 'Dual'; profile: string; width: number; domain: DomainId; router: string; concentrator?: string; slot?: number; source: 'Model-only' | 'Supplied IP' | 'Interface intent' };
export type Region = { id: string; target: string; base: number; size: number; attributes: string };
export type Draft = { id: string; revision: number; vcs: number; depth: number; endpoints: Endpoint[]; regions: Region[]; mappings: Record<string, { intended: boolean; permission: 'allow' | 'deny' }>; anchor: { x: number; y: number }; fromCandidate?: string };
export type Brief = { maxRuns: number; wallMinutes: number; concurrency: number; storageMiB: number; vcs: number[]; depths: number[]; arbiters: string[] };
export type AgentIntent = { endpoint: string; dataPolicy: 'local-only' | 'review-remote'; tokenReference: string; operations: string[] };
export function agentIntentErrors(intent: AgentIntent): string[] {
  const errors: string[] = [];
  try {
    const url = new URL(intent.endpoint);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) errors.push('Use an HTTP(S) endpoint without embedded credentials, query parameters, or fragments.');
    if (intent.dataPolicy === 'local-only' && !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) errors.push('Local-only intent requires a literal loopback or localhost endpoint.');
    if (intent.dataPolicy === 'review-remote' && url.protocol !== 'https:') errors.push('Remote-context intent requires HTTPS and a later explicit data review.');
  } catch { errors.push('Enter a valid endpoint URL.'); }
  if (intent.endpoint.length > 300 || !['local-only', 'review-remote'].includes(intent.dataPolicy)) errors.push('Invalid endpoint or data policy.');
  if (intent.tokenReference && !/^[A-Z][A-Z0-9_]{1,63}$/.test(intent.tokenReference)) errors.push('Provide only an environment-reference name, never a credential value.');
  if (!Array.isArray(intent.operations) || intent.operations.some(o => !['read-selection', 'read-artifacts', 'draft-changes', 'run-within-brief'].includes(o)) || new Set(intent.operations).size !== intent.operations.length) errors.push('Invalid or duplicate operation scope.');
  return errors;
}
export type LocalFinding = { id: string; question: string; outcome: 'Pass' | 'Violated' | 'Not evaluated'; detail: string; page: 'design/addresses' | 'design/endpoints' | 'design/domains' };
export type PrototypeState = { version: 1; draft: Draft; archives: Draft[]; selectedEndpoint: string; selectedCandidate: string; brief: Brief; approvedBrief: Brief | null; events: string[]; checks: { revision: number; findings: LocalFinding[] } | null; lastExport: { name: string; draft: Draft; content: string } | null; inputs: WorkingInputs; inputArchives: WorkingInputs[]; analysisRun: 'SIM-402' | 'SIM-451' | 'SIM-401'; agentIntent: AgentIntent | null }; 
export type Candidate = { id: string; name: string; run: string | null; vcs: number; depth: number; latency: number | null; throughput: number | null; status: 'Complete' | 'Partial' | 'Invalid' | 'Failed'; detail: string };

export const CANDIDATES: Candidate[] = [
  { id: 'BASE', name: 'Evaluated baseline', run: 'SIM-402', vcs: 2, depth: 8, latency: 28.6, throughput: 16.4, status: 'Complete', detail: 'Original network-model fixture; does not evaluate transaction P95.' },
  { id: 'C-14', name: 'Compact queues', run: 'SIM-442', vcs: 2, depth: 4, latency: 24.8, throughput: 18.9, status: 'Complete', detail: 'Lower queue capacity; comparable network-model observations.' },
  { id: 'C-09', name: 'Additional virtual channels', run: 'SIM-451', vcs: 4, depth: 8, latency: 22.4, throughput: 20.8, status: 'Complete', detail: 'Network performance fixture only; hardware generation support is not established.' },
  { id: 'C-22', name: 'Larger queues', run: 'SIM-468', vcs: 8, depth: 12, latency: 19.8, throughput: 21.9, status: 'Complete', detail: 'Exceeds the study queue-capacity gate. Remains inspectable and branchable.' },
  { id: 'C-27', name: 'Incomplete measurement', run: 'SIM-455', vcs: 4, depth: 12, latency: null, throughput: 19.5, status: 'Partial', detail: 'Packet-latency summary unavailable. Aggregate delivery remains available.' },
  { id: 'C-31', name: 'Unresolved attachment', run: null, vcs: 8, depth: 8, latency: null, throughput: null, status: 'Invalid', detail: 'Unresolved endpoint attachment; no evaluation was launched.' },
  { id: 'C-11', name: 'Interrupted evaluation', run: 'SIM-440', vcs: 2, depth: 16, latency: null, throughput: null, status: 'Failed', detail: 'Illustrative runner interruption; no complete performance measurements.' },
];
export const STUDY_QUEUE_LIMIT = 5120;
export const PAGES = [
  { id: 'flow/start', title: 'Start from a workload template', short: '1 · Workload', group: 'Flow', source: 'flow_start_workload' },
  { id: 'flow/tune', title: 'Workload intent', short: '2 · Workload intent', group: 'Flow', source: 'flow_fine_tune' },
  { id: 'flow/search', title: 'Evaluate & choose fabric', short: '3 · Choose fabric', group: 'Flow', source: 'flow_fabric_search' },
  { id: 'flow/compare', title: 'Choose a measured fabric', short: '4 · Choose fabric', group: 'Flow', source: 'flow_compare_versions' },
  { id: 'flow/optimize', title: 'Refine fabric parameters', short: '4 · Refine parameters', group: 'Flow', source: 'flow_optimize' },
  { id: 'flow/run', title: 'Finalize topology & RTL', short: '5 · Finalize & RTL', group: 'Flow', source: 'flow_run_analyze' },
  { id: 'design/editor', title: 'Design Editor', short: 'Editor', group: 'Design', source: 'design_editor' },
  { id: 'design/flow', title: 'Design Workflow', short: 'Design workflow', group: 'Design', source: 'design_workflow_flow' },
  { id: 'design/fabric-topology', title: 'Fabric Topology', short: 'Fabric topology', group: 'Design', source: 'design_fabric_topology' },
  { id: 'design/system', title: 'System / Block Diagram', short: 'System diagram', group: 'Design', source: 'design_system_block_diagram' },
  { id: 'design/catalog', title: 'Agent Catalog', short: 'Agent catalog', group: 'Design', source: 'design_ip_catalog' },
  { id: 'design/endpoints', title: 'Hardware Endpoints', short: 'Hardware endpoints', group: 'Design', source: 'design_hardware_endpoints' },
  { id: 'design/mapping', title: 'Initiator–Target Mapping', short: 'Initiator–target mapping', group: 'Design', source: 'design_initiator_target_mapping' },
  { id: 'design/agent-map', title: 'Agent Fabric Map', short: 'Agent fabric map', group: 'Design', source: 'design_agent_fabric_map' },
  { id: 'design/addresses', title: 'Address Map', short: 'Address map', group: 'Design', source: 'design_address_map' },
  { id: 'design/domains', title: 'Clock & Power Domains', short: 'Clock & power domains', group: 'Design', source: 'design_clock_power_domains' },
  { id: 'design/placement', title: 'Placement Constraints', short: 'Placement constraints', group: 'Design', source: 'design_placement_constraints' },
  { id: 'workloads/workflow', title: 'Project & Revision Workflow', short: 'Project workflow', group: 'Workloads & Requirements', source: 'workloads_requirements_project_workflow' },
  { id: 'workloads/library', title: 'Workload', short: 'Workload', group: 'Workloads & Requirements', source: 'workloads_requirements_workload_library' },
  { id: 'workloads/editor', title: 'Workload', short: 'Workload', group: 'Workloads & Requirements', source: 'workloads_requirements_structured_workload_editor' },
  { id: 'workloads/requirements', title: 'Requirements', short: 'Requirements', group: 'Workloads & Requirements', source: 'workloads_requirements_requirements_editor' },
  { id: 'workloads/bindings', title: 'Validate', short: 'Validate', group: 'Workloads & Requirements', source: 'workloads_requirements_endpoint_bindings' },
  { id: 'workloads/assumptions', title: 'Validate', short: 'Validate', group: 'Workloads & Requirements', source: 'workloads_requirements_assumptions_model_inputs' },
  { id: 'workloads/lowering', title: 'Validate', short: 'Validate', group: 'Workloads & Requirements', source: 'workloads_requirements_validation_lowering_preview' },
  { id: 'analysis/summary', title: 'Analysis Summary', short: 'Summary', group: 'Analysis', source: 'analysis_summary_sim_402' },
  { id: 'analysis/gr00t', title: 'GR00T Architecture Trace', short: 'GR00T trace', group: 'Analysis', source: 'analysis_gr00t_architecture_trace' },
  { id: 'analysis/fabric', title: 'Fabric Analysis', short: 'Fabric analysis', group: 'Analysis', source: 'analysis_fabric_static_checks' },
  { id: 'analysis/matrix', title: 'Traffic Matrix', short: 'Traffic matrix', group: 'Analysis', source: 'analysis_traffic_matrix_sim_402' },
  { id: 'analysis/missing', title: 'Traffic Matrix — Missing Artifact', short: 'Missing-artifact scenario', group: 'Analysis', source: 'analysis_traffic_matrix_sim_402_missing_artifact_corrected' },
  { id: 'analysis/topology', title: 'Topology & Simulation Overlay', short: 'Topology & simulation', group: 'Analysis', source: 'analysis_topology_overlay_sim_402' },
  { id: 'analysis/metrics', title: 'Analysis Metrics', short: 'Metrics', group: 'Analysis', source: 'analysis_metrics_sim_402' },
  { id: 'analysis/trace', title: 'Trace Viewer', short: 'Trace viewer', group: 'Analysis', source: 'analysis_trace_viewer_sim_402' },
  { id: 'analysis/curves', title: 'Curves & Pareto', short: 'Curves & Pareto', group: 'Analysis', source: 'analysis_curves_pareto' },
  { id: 'analysis/comparison', title: 'Run Comparison', short: 'Run comparison', group: 'Analysis', source: 'analysis_run_comparison_sim_402_vs_sim_401' },
  { id: 'explore/fabric', title: 'Fabric for This Workload', short: 'Fabric for workload', group: 'Explore', source: 'explore_project_fabric' },
  { id: 'explore/fabric-search', title: 'Reference Catalog', short: 'Reference catalog', group: 'Explore', source: 'explore_workload_search_recommendations' },
  { id: 'explore/ablations', title: 'Workload Ablations', short: 'Workload ablations', group: 'Explore', source: 'analysis_workload_ablations' },
  { id: 'explore/fabric-ablations', title: 'Fabric Ablations', short: 'Fabric ablations', group: 'Explore', source: 'explore_fabric_ablations' },
  { id: 'explore/brief', title: 'Revision Study (Advanced)', short: 'Revision study', group: 'Explore', source: 'explore_revision_recommendation_study' },
  { id: 'explore/progress', title: 'Study Execution & Budgets', short: 'Execution & budgets', group: 'Explore', source: 'explore_study_execution_budgets' },
  { id: 'explore/results', title: 'Candidate Results & Trade-offs', short: 'Candidate results', group: 'Explore', source: 'explore_candidate_results_trade_offs' },
  { id: 'explore/comparison', title: 'Candidate Comparison', short: 'Candidate comparison', group: 'Explore', source: 'explore_candidate_comparison' },
  { id: 'explore/adoption', title: 'Candidate Adoption / Branch', short: 'Adoption / branch', group: 'Explore', source: 'explore_candidate_adoption_branch' },
  { id: 'verify/overview', title: 'Evidence Overview', short: 'Evidence overview', group: 'Verify', source: 'verify_evidence_overview' },
  { id: 'verify/support', title: 'Configuration Support Checks', short: 'Configuration support', group: 'Verify', source: 'verify_configuration_support_checks' },
  { id: 'verify/checks', title: 'Check Setup & Results', short: 'Check setup & results', group: 'Verify', source: 'verify_check_setup_results' },
  { id: 'verify/obligations', title: 'Outstanding Obligations', short: 'Outstanding obligations', group: 'Verify', source: 'verify_outstanding_obligations' },
  { id: 'verify/evidence', title: 'Evidence Detail / Claim Scope', short: 'Evidence detail', group: 'Verify', source: 'verify_evidence_detail_claim_scope_evd_402_lat' },
  { id: 'deliver/readiness', title: 'Output Readiness', short: 'Output readiness', group: 'Deliver', source: 'deliver_output_readiness' },
  { id: 'deliver/configuration', title: 'Output Configuration', short: 'Output configuration', group: 'Deliver', source: 'deliver_output_configuration' },
  { id: 'deliver/job', title: 'Generation Job', short: 'Generation job', group: 'Deliver', source: 'deliver_generation_job' },
  { id: 'deliver/package', title: 'Package Review & Manifest', short: 'Package review', group: 'Deliver', source: 'deliver_package_review_manifest' },
  { id: 'deliver/artifacts', title: 'Artifact Inspection & Export', short: 'Artifact inspection', group: 'Deliver', source: 'deliver_artifact_inspection_export' },
  { id: 'shared/projects', title: 'Projects, Revisions & Recovery', short: 'Projects & revisions', group: 'Desktop', source: 'shared_projects_revisions_recovery' },
  { id: 'shared/environment', title: 'Environment & Local Settings', short: 'Environment & settings', group: 'Desktop', source: 'shared_environment_local_settings' },
  { id: 'shared/jobs', title: 'Jobs, Problems & Logs', short: 'Jobs, problems & logs', group: 'Desktop', source: 'shared_jobs_problems_logs_drawer' },
  { id: 'agents/assistant', title: 'Contextual Assistant', short: 'Contextual assistant', group: 'Optional agents', source: 'optional_agents_contextual_assistant' },
  { id: 'agents/runtime', title: 'Runtime Connection & Permissions', short: 'Connection & permissions', group: 'Optional agents', source: 'optional_agents_runtime_connection_permissions' },
  { id: 'agents/approvals', title: 'Approvals, Scope Changes & Activity', short: 'Approvals & activity', group: 'Optional agents', source: 'optional_agents_approvals_scope_changes_activity' },
  { id: 'agents/workload-translation', title: 'Requirements to Editable Workload', short: 'Workload translation', group: 'Optional agents', source: 'optional_agents_workload_translation' },
] as const;
export type PageId = typeof PAGES[number]['id'];
// Routes kept for old links and direct authoring, but no longer separate navigation
// entries: the same intent is now covered by Workload, Requirements, or Validate.
export const HIDDEN_PAGES = new Set<string>(['design/flow', 'design/system', 'design/endpoints', 'design/mapping', 'flow/compare', 'workloads/editor', 'workloads/bindings', 'workloads/assumptions', 'analysis/gr00t', 'analysis/fabric', 'explore/fabric', 'explore/fabric-search', 'explore/brief', 'verify/overview', 'verify/support', 'verify/checks', 'verify/obligations']);
// Verify and Deliver have live gateway surfaces; keep them in navigation.
// The fixture-era aliases inside each workspace are still filtered by LIVE_ALIASES.
export const HIDDEN_GROUPS = new Set<string>();
export const PAGE_ALIASES: Record<string, PageId> = {
  'workloads/editor': 'workloads/library',
  'workloads/bindings': 'workloads/lowering',
  'workloads/assumptions': 'workloads/lowering',
};
// Workspace roots are not pages themselves; resolve a bare #/analysis, #/explore,
// or #/design to that workspace's landing view instead of the generic not-found state.
export const WORKSPACE_HOME: Record<string, PageId> = {
  flow: 'flow/start',
  design: 'design/fabric-topology',
  workloads: 'workloads/workflow',
  analysis: 'analysis/summary',
  explore: 'explore/ablations',
  verify: 'verify/overview',
  deliver: 'deliver/readiness',
};
export function pageFromHash(hash: string) {
  const id = hash.replace(/^#\/?/, '');
  return PAGES.find(p => p.id === (id === 'flow/compare' ? 'flow/search' : id)) ?? PAGES.find(p => p.id === WORKSPACE_HOME[id]);
}
export function candidateById(id: string): Candidate { return CANDIDATES.find(c => c.id === id) ?? CANDIDATES[0]; }
export function queueFlits(c: Pick<Candidate, 'vcs' | 'depth'>) { return 16 * 5 * c.vcs * c.depth; }
export function rawGBps(bits: number, mhz: number) { return bits / 8 * mhz / 1000; }
export function hex(value: number) { return '0x' + value.toString(16).toUpperCase().padStart(12, '0').replace(/(.{4})(?=.)/g, '$1_'); }
export function sizeLabel(bytes: number) { return bytes >= 2 ** 30 ? `${(bytes / 2 ** 30).toFixed(2).replace(/\.00$/, '')} GiB` : bytes >= 2 ** 20 ? `${bytes / 2 ** 20} MiB` : bytes >= 1024 ? `${(bytes / 1024).toFixed(2).replace(/\.00$/, '')} KiB` : `${bytes} B`; }
export function parseAddress(input: string): number | null {
  if (!/^0x[\da-fA-F_]+$/.test(input)) return null;
  const n = Number.parseInt(input.replaceAll('_', '').slice(2), 16);
  return Number.isSafeInteger(n) && n >= 0 && n < 2 ** 48 ? n : null;
}
export function overlaps(regions: Region[]) {
  return regions.flatMap((a, i) => regions.slice(i + 1).filter(b => a.base < b.base + b.size && b.base < a.base + a.size).map(b => ({ a: a.id, b: b.id, start: Math.max(a.base, b.base), size: Math.min(a.base + a.size, b.base + b.size) - Math.max(a.base, b.base) })));
}
export function mappedBytes(regions: Region[]) {
  let total = 0, end = 0;
  for (const r of [...regions].sort((a, b) => a.base - b.base)) { total += Math.max(0, r.base + r.size - Math.max(end, r.base)); end = Math.max(end, r.base + r.size); }
  return total;
}
export function routeBetween(from: string, to: string) {
  if (!ROUTERS.includes(from) || !ROUTERS.includes(to)) return [];
  const [, row, col] = from.split('_').map(Number), [, targetRow, targetCol] = to.split('_').map(Number);
  let r = row, c = col;
  const path = [from];
  while (c !== targetCol) { c += Math.sign(targetCol - c); path.push(`R_${r}_${c}`); }
  while (r !== targetRow) { r += Math.sign(targetRow - r); path.push(`R_${r}_${c}`); }
  return path;
}
export function canAttach(endpoints: Endpoint[], id: string, router: string) {
  if (!ROUTERS.includes(router)) return false;
  const current = endpoints.find(e => e.id === id);
  if (current?.concentrator && current.router !== router) return false;
  return !endpoints.some(e => e.id !== id && e.router === router && !(current?.concentrator && e.concentrator === current.concentrator));
}
export function objectiveEligible(c: Candidate) { return c.status === 'Complete' && c.latency !== null && c.throughput !== null && c.throughput >= 18 && queueFlits(c) <= STUDY_QUEUE_LIMIT; }
export function frontier(candidates = CANDIDATES) {
  const eligible = candidates.filter(objectiveEligible);
  return eligible.filter(a => !eligible.some(b => b.id !== a.id && b.latency! <= a.latency! && queueFlits(b) <= queueFlits(a) && (b.latency! < a.latency! || queueFlits(b) < queueFlits(a)))).sort((a, b) => queueFlits(a) - queueFlits(b));
}
export function projectPoint(c: Candidate) {
  if (c.latency === null || c.status !== 'Complete') return null;
  return { x: 68 + queueFlits(c) / 8192 * 572, y: 326 - (c.latency - 18) / 16 * 274 };
}
export function criteria(c: Candidate) {
  return [
    { id: 'REQ-LAT-04', name: 'P95 transaction latency ≤ 25 ns', value: 'Not recorded', outcome: 'Not evaluated', reason: 'Packet P99 does not measure complete transaction P95.' },
    { id: 'REQ-THR-02', name: 'Aggregate delivered throughput ≥ 18 GB/s', value: c.throughput === null ? 'Unavailable' : `${c.throughput.toFixed(1)} GB/s`, outcome: c.throughput === null ? 'Not evaluated' : c.throughput >= 18 ? 'Met' : 'Violated', reason: 'Illustrative aggregate delivery summary · Phase 2.' },
    { id: 'STUDY-BUF-01', name: 'Study gate: configured queues ≤ 5,120 flits', value: `${queueFlits(c).toLocaleString()} flits`, outcome: queueFlits(c) <= STUDY_QUEUE_LIMIT ? 'Met' : 'Violated', reason: 'Declared storage capacity, not physical area or power.' },
  ];
}
export function briefSpace(b: Brief) { return b.vcs.length * b.depths.length * b.arbiters.length; }
export function briefErrors(b: Brief): string[] {
  const errors: string[] = [];
  if (![b.maxRuns, b.wallMinutes, b.concurrency, b.storageMiB].every(v => Number.isSafeInteger(v) && v > 0)) errors.push('Execution limits must be positive whole numbers.');
  if (b.maxRuns > 10000 || b.wallMinutes > 1440 || b.concurrency > 64 || b.storageMiB > 1048576) errors.push('Execution limits exceed this local preview’s input bounds.');
  if (!b.vcs.length || !b.depths.length || !b.arbiters.length) errors.push('Select at least one value for every search dimension.');
  if (new Set(b.vcs).size !== b.vcs.length || new Set(b.depths).size !== b.depths.length || new Set(b.arbiters).size !== b.arbiters.length) errors.push('Search dimensions must contain unique values.');
  if (b.vcs.some(n => ![2, 4, 8].includes(n)) || b.depths.some(n => ![4, 8, 12, 16].includes(n)) || b.arbiters.some(a => !['Round robin', 'Age priority'].includes(a))) errors.push('A search dimension is outside the declared preview envelope.');
  if (b.maxRuns > briefSpace(b)) errors.push('Maximum runs exceeds the unique configurations in this preview (one seed, no repetitions).');
  return errors;
}
export function makeDraft(): Draft {
  const endpoints: Endpoint[] = [
    { id: 'EP_NPU_0', role: 'Initiator', profile: 'AXI interface intent', width: 128, domain: 'clk_fabric', router: 'R_1_2', concentrator: 'CONC_A', slot: 0, source: 'Model-only' },
    { id: 'EP_NPU_1', role: 'Initiator', profile: 'AXI interface intent', width: 128, domain: 'clk_fabric', router: 'R_1_2', concentrator: 'CONC_A', slot: 1, source: 'Model-only' },
    { id: 'EP_NPU_2', role: 'Initiator', profile: 'AXI interface intent', width: 128, domain: 'clk_fabric', router: 'R_2_1', source: 'Model-only' },
    { id: 'EP_NPU_3', role: 'Initiator', profile: 'AXI interface intent', width: 128, domain: 'clk_fabric', router: 'R_2_2', source: 'Model-only' },
    { id: 'EP_HBM_0', role: 'Target', profile: 'Memory interface intent', width: 256, domain: 'clk_memory', router: 'R_0_0', source: 'Supplied IP' },
    { id: 'EP_HBM_1', role: 'Target', profile: 'Memory interface intent', width: 256, domain: 'clk_memory', router: 'R_0_3', source: 'Supplied IP' },
    { id: 'EP_HOST', role: 'Dual', profile: 'Host interface intent', width: 128, domain: 'clk_host', router: 'R_3_3', source: 'Supplied IP' },
    { id: 'EP_DMA', role: 'Initiator', profile: 'DMA interface intent', width: 128, domain: 'clk_fabric', router: 'R_3_0', source: 'Model-only' },
  ];
  const regions: Region[] = [
    { id: 'BOOT_ROM', target: 'External ROM intent', base: 0, size: 2 * 2 ** 20, attributes: 'Read-only' },
    { id: 'SYS_SRAM', target: 'External SRAM intent', base: 0x200000, size: 16 * 2 ** 20, attributes: 'Read/write' },
    { id: 'PERIPH_MMIO', target: 'External peripheral intent', base: 0x2000000, size: 224 * 2 ** 20, attributes: 'Device' },
    { id: 'NPU_WEIGHTS', target: 'Compute memory window intent', base: 0x80000000, size: 2 ** 30, attributes: 'Read/write' },
    { id: 'PCIE_BAR0', target: 'EP_HOST', base: 0xb0000000, size: 512 * 2 ** 20, attributes: 'Non-cacheable' },
    { id: 'HBM_CH0', target: 'EP_HBM_0', base: 0x100000000000, size: 16 * 2 ** 30, attributes: 'Memory' },
    { id: 'HBM_CH1', target: 'EP_HBM_1', base: 0x100400000000, size: 16 * 2 ** 30, attributes: 'Memory' },
  ];
  const mappings = Object.fromEntries(endpoints.filter(e => e.role !== 'Target').flatMap(e => ['EP_HBM_0', 'EP_HBM_1'].map(target => [`${e.id}:${target}`, { intended: true, permission: e.id === 'EP_HOST' && target === 'EP_HBM_1' ? 'deny' as const : 'allow' as const }])));
  return { id: 'local-draft', revision: 1, vcs: 2, depth: 8, endpoints, regions, mappings, anchor: { x: 3000, y: 1800 } };
}
export function initialState(): PrototypeState {
  return { version: 1, draft: makeDraft(), archives: [], selectedEndpoint: 'EP_NPU_0', selectedCandidate: 'C-09', brief: { maxRuns: 24, wallMinutes: 90, concurrency: 4, storageMiB: 1024, vcs: [2, 4, 8], depths: [4, 8, 12, 16], arbiters: ['Round robin', 'Age priority'] }, approvedBrief: null, events: ['Opened the local illustrative workspace. No backend run was launched.'], checks: null, lastExport: null, inputs: initialInputs(), inputArchives: [], analysisRun: 'SIM-402', agentIntent: null };
}
export function event(s: PrototypeState, message: string): PrototypeState { return { ...s, events: [message, ...s.events].slice(0, 100) }; }
export function editDraft(s: PrototypeState, message: string, mutate: (draft: Draft) => Draft): PrototypeState {
  return event({ ...s, draft: { ...mutate(s.draft), revision: s.draft.revision + 1 } }, message);
}
export function branchCandidate(s: PrototypeState, c: Candidate, expectedRevision: number): PrototypeState {
  if (s.draft.revision !== expectedRevision) throw new Error('The active draft changed. Close and review the adoption again.');
  if (c.status !== 'Complete') throw new Error('Only a completely measured fixture can be branched in this prototype.');
  if (s.archives.length >= 20) throw new Error('This preview stores up to 20 prior drafts. Export your work before resetting.');
  const sequence = s.archives.length + 1;
  const draft = { ...makeDraft(), id: `branch-${c.id.toLowerCase()}-${sequence}`, revision: s.draft.revision + 1, vcs: c.vcs, depth: c.depth, fromCandidate: c.id };
  const selectedEndpoint = draft.endpoints.some(e => e.id === s.selectedEndpoint) ? s.selectedEndpoint : draft.endpoints[0].id;
  return event({ ...s, selectedEndpoint, archives: [...s.archives, structuredClone(s.draft)], draft }, `Created local branch from ${c.id}; previous draft preserved. No hardware was generated.`);
}
export function patchCandidate(s: PrototypeState, c: Candidate, expectedRevision: number): PrototypeState {
  if (s.draft.revision !== expectedRevision) throw new Error('The active draft changed. Review the patch again.');
  if (c.status !== 'Complete') throw new Error('Incomplete candidate evidence cannot be patched in this preview.');
  const base = makeDraft();
  if ((s.draft.vcs !== base.vcs && s.draft.vcs !== c.vcs) || (s.draft.depth !== base.depth && s.draft.depth !== c.depth)) throw new Error('The active queue configuration conflicts with this proposal. Use a separate branch.');
  return editDraft(s, `Applied ${c.id} queue parameters locally; unrelated draft edits preserved. Evaluation required.`, d => ({ ...d, vcs: c.vcs, depth: c.depth, fromCandidate: c.id }));
}
function validDraft(value: unknown): value is Draft {
  if (!value || typeof value !== 'object') return false;
  const d = value as Draft;
  if (typeof d.id !== 'string' || d.id.length > 80 || !Number.isSafeInteger(d.revision) || d.revision < 1 || ![2, 4, 8].includes(d.vcs) || ![4, 8, 12, 16].includes(d.depth)) return false;
  if (!d.anchor || ![d.anchor.x, d.anchor.y].every(v => Number.isFinite(v) && v >= 0 && v <= 4800)) return false;
  if (!Array.isArray(d.endpoints) || d.endpoints.length < 1 || d.endpoints.length > 100 || !d.endpoints.every(e => e && typeof e.id === 'string' && /^[A-Z][A-Z0-9_]{1,40}$/.test(e.id) && ['Initiator', 'Target', 'Dual'].includes(e.role) && typeof e.profile === 'string' && e.profile.length < 100 && [64, 128, 256, 512].includes(e.width) && DOMAIN_IDS.includes(e.domain) && ROUTERS.includes(e.router) && ['Model-only', 'Supplied IP', 'Interface intent'].includes(e.source) && (e.concentrator === undefined || (typeof e.concentrator === 'string' && Number.isInteger(e.slot))))) return false;
  if (new Set(d.endpoints.map(e => e.id)).size !== d.endpoints.length) return false;
  if (!Array.isArray(d.regions) || d.regions.length > 100 || !d.regions.every(r => r && typeof r.id === 'string' && typeof r.target === 'string' && typeof r.attributes === 'string' && Number.isSafeInteger(r.base) && r.base >= 0 && Number.isSafeInteger(r.size) && r.size > 0 && r.base + r.size <= 2 ** 48)) return false;
  if (new Set(d.regions.map(r => r.id)).size !== d.regions.length) return false;
  return !!d.mappings && typeof d.mappings === 'object' && Object.values(d.mappings).every(m => m && typeof m.intended === 'boolean' && ['allow', 'deny'].includes(m.permission));
}
export function restoreState(raw: string | null): { state: PrototypeState; warning: string | null } {
  if (!raw) return { state: initialState(), warning: null };
  try {
    const s = JSON.parse(raw) as PrototypeState;
    // Additive v1 migration: preserve existing drafts while introducing working-input editors.
    if (!Object.hasOwn(s, 'inputs')) s.inputs = initialInputs();
    if (!Object.hasOwn(s, 'inputArchives')) s.inputArchives = [];
    if (!Object.hasOwn(s, 'analysisRun')) s.analysisRun = 'SIM-402';
    if (!Object.hasOwn(s, 'agentIntent')) s.agentIntent = null;
    if (s.agentIntent !== null && (!s.agentIntent || agentIntentErrors(s.agentIntent).length)) throw new Error('Invalid agent connection intent');
    if (!['SIM-402', 'SIM-451', 'SIM-401'].includes(s.analysisRun)) throw new Error('Invalid analysis fixture reference');
    if (!validInputs(s.inputs) || !Array.isArray(s.inputArchives) || s.inputArchives.length > 20 || !s.inputArchives.every(validInputs)) throw new Error('Invalid workload inputs');
    if (s.version !== 1 || !validDraft(s.draft) || !Array.isArray(s.archives) || s.archives.length > 20 || !s.archives.every(validDraft) || !s.draft.endpoints.some(e => e.id === s.selectedEndpoint) || !CANDIDATES.some(c => c.id === s.selectedCandidate) || !Array.isArray(s.events) || !s.events.every(e => typeof e === 'string' && e.length <= 1000) || !s.brief || briefErrors(s.brief).length || (s.approvedBrief !== null && (!s.approvedBrief || briefErrors(s.approvedBrief).length))) throw new Error('Invalid local fixture');
    if (s.checks !== null && (!s.checks || !Number.isSafeInteger(s.checks.revision) || !Array.isArray(s.checks.findings) || !s.checks.findings.every(f => f && typeof f.id === 'string' && typeof f.question === 'string' && typeof f.detail === 'string' && ['Pass', 'Violated', 'Not evaluated'].includes(f.outcome) && ['design/addresses', 'design/endpoints', 'design/domains'].includes(f.page)))) throw new Error('Invalid check record');
    if (s.lastExport !== null && (!s.lastExport || !validDraft(s.lastExport.draft) || typeof s.lastExport.name !== 'string' || !/^[a-zA-Z0-9_-]+\.json$/.test(s.lastExport.name) || typeof s.lastExport.content !== 'string')) throw new Error('Invalid export record');
    if (s.lastExport) JSON.parse(s.lastExport.content);
    return { state: s, warning: null };
  } catch { return { state: initialState(), warning: 'Saved preview data could not be read. A fresh fixture is shown; the original stored value was not overwritten.' }; }
}
