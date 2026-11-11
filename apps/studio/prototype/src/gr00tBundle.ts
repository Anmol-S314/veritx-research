export const GR00T_SCHEMA = 'veritx/gr00t-static-architecture-observation/1';
export const GR00T_BUNDLE_SCHEMA = 'veritx/gr00t-static-architecture-bundle/1';

export type Gr00tObservation = {
  schema: typeof GR00T_SCHEMA;
  qualification: string;
  source: { dataset_repo: string; revision: string; subset: string; episode: number; frame_index: number; timestamp_s: number; dataset_task: string; camera_sha256: string; state_sha256: string };
  model: { repo: string; revision: string; export_prompt: string; prompt_source: string; flow_matching_steps: number; simulation_horizon_s: number; staticpredict_horizon: number };
  coverage: { graph_nodes: number; numeric_inference: string; timeloop_mapped_nodes: number; traffic_trace: string; timeloop_matrix_candidates?: number; timeloop_unresolved_shape_nodes?: number; timeloop_unsupported_nodes?: number; timeloop_unique_signatures?: number };
  model_graphs: Record<string, { node_count: number; onnx_sha256: string; operator_counts: Record<string, number>; operators: { id: string; op_type: string; inputs: unknown[]; outputs: unknown[]; timeloop_mapping?: { status: string; signature_id?: string; batch_count?: number; M?: number; N?: number; K?: number; precision_bits?: number; single_matrix_actual_computes?: number; single_matrix_modeled_cycles?: number } }[]; inputs: { name: string; shape?: number[]; dtype?: string }[]; outputs: { name: string; shape?: number[]; dtype?: string }[]; timeloop_mapped_node_count: number; timeloop_status: string }>;
  roi_simulation?: {
    qualification: string; model_onnx_sha256: string; source_graph: string; node_name: string; graph_node_index: number; operator: string;
    input_shapes: number[][]; output_shape: number[]; dtype: string; precision_bits: number; batch_count: number;
    timeloop_single_batch_problem: { M: number; N: number; K: number; actual_computes: number; modeled_cycles: number; resolved_word_bits: number[]; stats_filename: string; stats_sha256: string; config_sha256: string };
    traffic: { payload_bytes: number; padded_bytes: number; packets: number; flits: number; trace_sha256: string };
    booksim_variants: { layout: string; observed: { packets: number; flits: number; request_latency_avg: number; request_latency_p50: number; request_latency_p95: number; request_latency_p99: number; last_arrival_cycle: number } }[];
  };
  full_static_mapping?: { schema: string; qualification: string; unique_signatures: number; mapped_matrix_nodes: number; unresolved_shape_matrix_nodes: number; unsupported_operator_nodes: number; source_inventory_sha256: string; signatures: { signature_id: string; M: number; N: number; K: number; precision_bits: number; single_matrix_actual_computes: number; single_matrix_modeled_cycles: number; config_sha256: string; stats_sha256: string; mapped_node_count: number }[]; limitations: string[] };
  topology_sweep?: { schema: string; qualification: string; source_roi_result_sha256: string; trace_sha256: string; trace_packets: number; trace_flits: number; reproduction: { tool_sha256: string; booksim_binary_sha256: string; command: string }; endpoint_binding: Record<string, string>; shared_router_overrides: Record<string, number>; ranking_metric: string; rankings_by_endpoint_count: Record<string, string[]>; variants: { status: 'completed' | 'failed'; topology: { name: string; backend: string; routing: string; params: Record<string, number>; endpoints: number; edges: number }; trace_sha256: string; config_sha256: string; packet_log_sha256?: string; observed?: { packets: number; flits: number; request_latency_avg: number; request_latency_p95: number; last_arrival_cycle: number }; error?: string }[]; limitations: string[] };
  srota_comparison?: { schema: string; qualification: string; source_roi_result_sha256: string; trace_sha256: string; trace_packets: number; trace_flits: number; reproduction: { tool_sha256: string; srota_template_sha256: string; booksim_binary_sha256: string }; endpoint_binding: Record<string, string>; shared_router_settings: Record<string, number | string>; variants: { name: string; topology: { backend: string; routing: string; params: Record<string, string | number> }; endpoints: number; trace_sha256: string; config_sha256: string; packet_log_sha256: string; observed: { packets: number; flits: number; request_latency_avg: number; request_latency_p95: number; last_arrival_cycle: number } }[]; limitations: string[] };
  semantics: string[];
};
export type Gr00tManifest = { schema: typeof GR00T_BUNDLE_SCHEMA; files: Record<string, string>; model_graphs: Record<string, string>; reproduction: { dataset_revision: string; frame_index: number; model_revision: string } };
const sha256 = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const revision = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{40}$/.test(v);
const obj = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
function validTensor(v: unknown): boolean {
  return obj(v) && typeof v.name === 'string' && Array.isArray(v.shape) && v.shape.every((d: unknown) => d === null || Number.isSafeInteger(d) && (d as number) >= 0);
}

export function validateGr00tObservation(v: unknown): Gr00tObservation {
  if (!obj(v) || v.schema !== GR00T_SCHEMA || v.qualification !== 'OFFLINE_OBSERVATION_ARCHITECTURE_TRACE_ONLY') throw new Error('Unsupported GR00T observation schema or qualification.');
  const source = v.source, model = v.model, coverage = v.coverage, graphs = v.model_graphs;
  if (!obj(source) || !obj(model) || !obj(coverage) || !obj(graphs)) throw new Error('Bundle is missing source, model, coverage, or graph data.');
  if (typeof source.dataset_repo !== 'string' || typeof source.dataset_task !== 'string' || typeof source.subset !== 'string' || !Number.isSafeInteger(source.episode) || !Number.isSafeInteger(source.frame_index) || !finite(source.timestamp_s) || !sha256(source.camera_sha256) || !sha256(source.state_sha256) || !revision(source.revision)) throw new Error('Invalid dataset observation identity or digest.');
  if (typeof model.repo !== 'string' || !revision(model.revision) || typeof model.export_prompt !== 'string' || typeof model.prompt_source !== 'string' || !Number.isSafeInteger(model.flow_matching_steps) || !finite(model.simulation_horizon_s) || !Number.isSafeInteger(model.staticpredict_horizon)) throw new Error('Invalid model identity or architecture metadata.');
  if (!Number.isSafeInteger(coverage.graph_nodes) || coverage.graph_nodes < 1 || !Number.isSafeInteger(coverage.timeloop_mapped_nodes) || coverage.timeloop_mapped_nodes < 0 || coverage.timeloop_mapped_nodes > coverage.graph_nodes || typeof coverage.numeric_inference !== 'string' || typeof coverage.traffic_trace !== 'string') throw new Error('Invalid architecture coverage.');
  const totals = Object.values(graphs).reduce((acc, g: any) => {
    if (!obj(g) || !Number.isSafeInteger(g.node_count) || g.node_count < 0 || !sha256(g.onnx_sha256) || !obj(g.operator_counts) || !Array.isArray(g.operators) || g.operators.length !== g.node_count || !Number.isSafeInteger(g.timeloop_mapped_node_count) || g.timeloop_mapped_node_count < 0 || g.timeloop_mapped_node_count > g.node_count || typeof g.timeloop_status !== 'string' || !Array.isArray(g.inputs) || !g.inputs.every(validTensor) || !Array.isArray(g.outputs) || !g.outputs.every(validTensor)) throw new Error('Invalid graph or operator trace.');
    const counts = Object.entries(g.operator_counts).reduce((sum, [op, count]) => {
      if (!op || !Number.isSafeInteger(count) || (count as number) < 0) throw new Error('Invalid operator count.'); return sum + (count as number);
    }, 0);
    if (counts !== g.node_count || g.operators.some((op: any) => !obj(op) || typeof op.id !== 'string' || typeof op.op_type !== 'string' || !Array.isArray(op.inputs) || !op.inputs.every(validTensor) || !Array.isArray(op.outputs) || !op.outputs.every(validTensor))) throw new Error('Operator rows do not reconcile with graph counts.');
    return { nodes: acc.nodes + g.node_count, mapped: acc.mapped + g.timeloop_mapped_node_count };
  }, { nodes: 0, mapped: 0 });
  if (totals.nodes !== coverage.graph_nodes || totals.mapped !== coverage.timeloop_mapped_nodes || !Array.isArray(v.semantics) || v.semantics.some((s: unknown) => typeof s !== 'string')) throw new Error('Graph coverage does not reconcile.');
  if (v.roi_simulation !== undefined) {
    const roi = v.roi_simulation;
    if (!obj(roi) || roi.qualification !== 'SOURCE_DERIVED_STATIC_ROI_SIMULATION' || !sha256(roi.model_onnx_sha256) || !obj(graphs[roi.source_graph]) || roi.model_onnx_sha256 !== graphs[roi.source_graph].onnx_sha256 || typeof roi.node_name !== 'string' || typeof roi.operator !== 'string' || !Number.isSafeInteger(roi.graph_node_index) || roi.graph_node_index < 0 || roi.graph_node_index >= graphs[roi.source_graph].operators.length || graphs[roi.source_graph].operators[roi.graph_node_index].op_type !== roi.operator || !Array.isArray(roi.input_shapes) || !Array.isArray(roi.output_shape) || typeof roi.dtype !== 'string' || !Number.isSafeInteger(roi.precision_bits) || roi.precision_bits < 1 || !Number.isSafeInteger(roi.batch_count) || !obj(roi.timeloop_single_batch_problem) || !obj(roi.traffic) || !Array.isArray(roi.booksim_variants) || roi.booksim_variants.length !== 2) throw new Error('Invalid source-derived ROI simulation.');
    const problem = roi.timeloop_single_batch_problem, traffic = roi.traffic;
    if (![problem.M, problem.N, problem.K, problem.actual_computes, problem.modeled_cycles].every(Number.isSafeInteger) || problem.M < 1 || problem.N < 1 || problem.K < 1 || problem.actual_computes !== problem.M * problem.N * problem.K || !Array.isArray(problem.resolved_word_bits) || problem.resolved_word_bits.length !== 4 || problem.resolved_word_bits.some((bits: unknown) => bits !== roi.precision_bits) || !sha256(problem.stats_sha256) || !sha256(problem.config_sha256) || ![traffic.payload_bytes, traffic.padded_bytes, traffic.packets, traffic.flits].every(Number.isSafeInteger) || traffic.payload_bytes < 1 || traffic.padded_bytes < traffic.payload_bytes || traffic.packets < 1 || traffic.flits < traffic.packets || !sha256(traffic.trace_sha256)) throw new Error('Invalid ROI simulation metrics or trace conservation.');
    const variants = roi.booksim_variants;
    if (variants.some((variant: any) => !obj(variant) || typeof variant.layout !== 'string' || !obj(variant.observed) || variant.observed.packets !== traffic.packets || variant.observed.flits !== traffic.flits || !finite(variant.observed.request_latency_avg) || !Number.isSafeInteger(variant.observed.last_arrival_cycle)) || new Set(variants.map((variant: any) => variant.layout)).size !== 2) throw new Error('BookSim variants do not reconcile to the common ROI trace.');
  }
  if (v.full_static_mapping !== undefined) {
    const mapping = v.full_static_mapping;
    if (!obj(mapping) || mapping.schema !== 'veritx/gr00t-full-static-mapping/1' ||
        !Number.isSafeInteger(mapping.unique_signatures) || mapping.unique_signatures < 1 ||
        !Number.isSafeInteger(mapping.mapped_matrix_nodes) || mapping.mapped_matrix_nodes < 1 ||
        !Number.isSafeInteger(mapping.unresolved_shape_matrix_nodes) || mapping.unresolved_shape_matrix_nodes < 0 ||
        !Number.isSafeInteger(mapping.unsupported_operator_nodes) || mapping.unsupported_operator_nodes < 0 ||
        !sha256(mapping.source_inventory_sha256) || !Array.isArray(mapping.limitations) ||
        !Number.isSafeInteger(coverage.timeloop_matrix_candidates) ||
        !Number.isSafeInteger(coverage.timeloop_unresolved_shape_nodes) ||
        !Number.isSafeInteger(coverage.timeloop_unsupported_nodes) ||
        !Number.isSafeInteger(coverage.timeloop_unique_signatures) || !Array.isArray(mapping.signatures) ||
        mapping.signatures.length !== mapping.unique_signatures) throw new Error('Invalid full static mapping coverage.');
    const signatures = new Map<string, any>();
    for (const signature of mapping.signatures) {
      if (!obj(signature) || typeof signature.signature_id !== 'string' || !signature.signature_id ||
          ![signature.M, signature.N, signature.K, signature.precision_bits,
            signature.single_matrix_actual_computes, signature.single_matrix_modeled_cycles,
            signature.mapped_node_count].every(Number.isSafeInteger) ||
          signature.M < 1 || signature.N < 1 || signature.K < 1 || signature.precision_bits < 1 ||
          signature.single_matrix_actual_computes !== signature.M * signature.N * signature.K ||
          signature.mapped_node_count < 1 || !sha256(signature.config_sha256) || !sha256(signature.stats_sha256) ||
          signatures.has(signature.signature_id)) throw new Error('Invalid full mapping signature evidence.');
      signatures.set(signature.signature_id, signature);
    }
    const usedSignatures = new Map<string, number>();
    let actualDynamic = 0, actualUnsupported = 0;
    const mapped = Object.values(graphs).reduce((sum, graph: any) => {
      const rows = graph.operators.map((op: any) => op.timeloop_mapping);
      if (rows.some((row: any) => !obj(row) || typeof row.status !== 'string' || !row.status)) throw new Error('Full mapping is missing per-node status.');
      const count = rows.filter((row: any) => row.status === 'mapped').length;
      actualDynamic += rows.filter((row: any) => row.status === 'unresolved_shape').length;
      actualUnsupported += rows.filter((row: any) => row.status !== 'mapped' && row.status !== 'unresolved_shape').length;
      if (count !== graph.timeloop_mapped_node_count || rows.some((row: any) => {
        if (row.status !== 'mapped') return false;
        const signature = signatures.get(row.signature_id);
        if (typeof row.signature_id !== 'string' || !signature || !Number.isSafeInteger(row.batch_count) ||
            row.batch_count < 1 || row.M !== signature.M || row.N !== signature.N || row.K !== signature.K ||
            row.precision_bits !== signature.precision_bits ||
            row.single_matrix_actual_computes !== signature.single_matrix_actual_computes ||
            row.single_matrix_modeled_cycles !== signature.single_matrix_modeled_cycles) return true;
        usedSignatures.set(row.signature_id, (usedSignatures.get(row.signature_id) ?? 0) + 1);
        return false;
      })) throw new Error('Per-node Timeloop mapping does not reconcile.');
      return sum + count;
    }, 0);
    if (signatures.size !== coverage.timeloop_unique_signatures ||
        [...signatures].some(([id, signature]) => usedSignatures.get(id) !== signature.mapped_node_count) ||
        mapped !== coverage.timeloop_mapped_nodes || mapped !== mapping.mapped_matrix_nodes ||
        mapping.unresolved_shape_matrix_nodes !== coverage.timeloop_unresolved_shape_nodes ||
        mapping.unresolved_shape_matrix_nodes !== actualDynamic ||
        mapping.unsupported_operator_nodes !== coverage.timeloop_unsupported_nodes ||
        mapping.unsupported_operator_nodes !== actualUnsupported ||
        mapping.unique_signatures !== coverage.timeloop_unique_signatures ||
        coverage.timeloop_matrix_candidates !== mapped + mapping.unresolved_shape_matrix_nodes) throw new Error('Full mapping coverage totals do not reconcile.');
  }
  if (v.topology_sweep !== undefined) {
    const sweep = v.topology_sweep;
    const declared = ['mesh_4x4', 'mesh_8x8', 'torus_8x8', 'flatfly_64',
      'gec_express_k8', 'gec_mecs_k8', 'gec_mesh_k8'];
    if (!obj(sweep) || sweep.schema !== 'veritx/gr00t-topology-sweep/1' ||
        sweep.qualification !== 'DIAGNOSTIC_OPEN_LOOP_ROI_TOPOLOGY_COMPARISON' ||
        !sha256(sweep.source_roi_result_sha256) || !sha256(sweep.trace_sha256) ||
        !obj(v.roi_simulation) || sweep.trace_sha256 !== v.roi_simulation.traffic.trace_sha256 ||
        sweep.trace_packets !== v.roi_simulation.traffic.packets || sweep.trace_flits !== v.roi_simulation.traffic.flits ||
        !obj(sweep.endpoint_binding) || !obj(sweep.shared_router_overrides) ||
        !Array.isArray(sweep.variants) || sweep.variants.length !== declared.length ||
        !obj(sweep.rankings_by_endpoint_count) || !Array.isArray(sweep.limitations) ||
        !sha256(sweep.reproduction?.tool_sha256) || !sha256(sweep.reproduction?.booksim_binary_sha256))
      throw new Error('Invalid same-trace topology sweep.');
    const names = new Set<string>(), groups = new Map<string, any[]>();
    for (const row of sweep.variants) {
      if (!obj(row) || !obj(row.topology) || !declared.includes(row.topology.name) || names.has(row.topology.name) ||
          typeof row.topology.backend !== 'string' || typeof row.topology.routing !== 'string' ||
          !obj(row.topology.params) || !Number.isSafeInteger(row.topology.endpoints) || row.topology.endpoints < 3 ||
          !Number.isSafeInteger(row.topology.edges) || row.topology.edges < 1 ||
          row.trace_sha256 !== sweep.trace_sha256 || !sha256(row.config_sha256))
        throw new Error('Invalid topology variant identity or trace.');
      names.add(row.topology.name);
      if (row.status === 'completed') {
        if (!sha256(row.packet_log_sha256) || !obj(row.observed) ||
            row.observed.packets !== sweep.trace_packets || row.observed.flits !== sweep.trace_flits ||
            !finite(row.observed.request_latency_avg) || !finite(row.observed.request_latency_p95) ||
            !Number.isSafeInteger(row.observed.last_arrival_cycle)) throw new Error('Topology variant does not conserve the shared trace.');
        const count = String(row.topology.endpoints), rows = groups.get(count) ?? [];
        rows.push(row); groups.set(count, rows);
      } else if (row.status !== 'failed' || typeof row.error !== 'string') {
        throw new Error('Invalid topology variant status.');
      }
    }
    if (declared.some(name => !names.has(name))) throw new Error('Topology sweep omitted a declared preset.');
    const expectedRanks = Object.fromEntries([...groups.entries()].sort(([a], [b]) => Number(a) - Number(b)).map(([count, rows]) => [count,
      rows.sort((a, b) => a.observed.request_latency_avg - b.observed.request_latency_avg ||
        a.observed.request_latency_p95 - b.observed.request_latency_p95 ||
        a.topology.name.localeCompare(b.topology.name)).map(row => row.topology.name)]));
    if (JSON.stringify(expectedRanks) !== JSON.stringify(sweep.rankings_by_endpoint_count)) throw new Error('Topology ranking does not match retired request latency.');
  }
  if (v.srota_comparison !== undefined) {
    const pair = v.srota_comparison;
    const expectedNames = ['mesh_8x8_vc4', 'srota_8x8'];
    if (!obj(pair) || pair.schema !== 'veritx/gr00t-srota-paired-comparison/1' ||
        pair.qualification !== 'DIAGNOSTIC_OPEN_LOOP_ROI_PAIR' || !obj(v.roi_simulation) ||
        !sha256(pair.source_roi_result_sha256) || !sha256(pair.trace_sha256) ||
        pair.trace_sha256 !== v.roi_simulation.traffic.trace_sha256 ||
        pair.trace_packets !== v.roi_simulation.traffic.packets || pair.trace_flits !== v.roi_simulation.traffic.flits ||
        !obj(pair.reproduction) || !sha256(pair.reproduction.tool_sha256) ||
        !sha256(pair.reproduction.srota_template_sha256) || !sha256(pair.reproduction.booksim_binary_sha256) ||
        !obj(pair.shared_router_settings) || pair.shared_router_settings.num_vcs !== 4 ||
        pair.shared_router_settings.vc_buf_size !== 8 || pair.shared_router_settings.routing_delay !== 1 ||
        !Array.isArray(pair.variants) || pair.variants.length !== 2 || !Array.isArray(pair.limitations))
      throw new Error('Invalid same-trace SROTA comparison.');
    const names = new Set<string>();
    for (const row of pair.variants) {
      if (!obj(row) || !expectedNames.includes(row.name) || names.has(row.name) ||
          !obj(row.topology) || row.endpoints !== 64 || row.trace_sha256 !== pair.trace_sha256 ||
          !sha256(row.config_sha256) || !sha256(row.packet_log_sha256) || !obj(row.observed) ||
          row.observed.packets !== pair.trace_packets || row.observed.flits !== pair.trace_flits ||
          !finite(row.observed.request_latency_avg) || !Number.isSafeInteger(row.observed.request_latency_p95) ||
          !Number.isSafeInteger(row.observed.last_arrival_cycle)) throw new Error('SROTA pair does not conserve the common ROI trace.');
      names.add(row.name);
    }
    if (expectedNames.some(name => !names.has(name))) throw new Error('SROTA comparison omitted its matched mesh control.');
  }
  return v as Gr00tObservation;
}
export function validateGr00tManifest(v: unknown, observation: Gr00tObservation): Gr00tManifest {
  if (!obj(v) || v.schema !== GR00T_BUNDLE_SCHEMA || !obj(v.files) || !obj(v.model_graphs) || !obj(v.reproduction)) throw new Error('Unsupported or incomplete bundle manifest.');
  if (!sha256(v.files['comparison.json']) || !sha256(v.files['observation.rgb24']) || !revision(v.reproduction.dataset_revision) || !revision(v.reproduction.model_revision) || !Number.isSafeInteger(v.reproduction.frame_index)) throw new Error('Invalid manifest digests or reproduction identity.');
  for (const [name, graph] of Object.entries(observation.model_graphs)) if (v.model_graphs[name] !== graph.onnx_sha256) throw new Error(`Manifest does not match ONNX graph ${name}.`);
  if (v.reproduction.dataset_revision !== observation.source.revision || v.reproduction.frame_index !== observation.source.frame_index || v.reproduction.model_revision !== observation.model.revision) throw new Error('Manifest and observation identities do not match.');
  return v as Gr00tManifest;
}
export async function sha256File(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
}
