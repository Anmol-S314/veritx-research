import { describe, expect, it } from 'vitest';
import comparison from '../../../../runs/gr00t-model/staticpick-v1-observation/comparison.json';
import manifest from '../../../../runs/gr00t-model/staticpick-v1-observation/manifest.json';
import { validateGr00tManifest, validateGr00tObservation } from './gr00tBundle';

describe('GR00T recorded architecture bundle validation', () => {
  it('accepts the generated observation and matching manifest', () => {
    const obs = validateGr00tObservation(comparison);
    expect(validateGr00tManifest(manifest, obs).reproduction.frame_index).toBe(1);
    expect(obs.coverage.graph_nodes).toBe(12116);
    expect(obs.coverage.timeloop_mapped_nodes).toBe(1222);
    expect(obs.roi_simulation?.node_name).toBe('node_MatMul_916');
    expect(obs.roi_simulation?.timeloop_single_batch_problem.resolved_word_bits).toEqual([32, 32, 32, 32]);
    expect(obs.full_static_mapping?.mapped_matrix_nodes).toBe(1222);
    expect(obs.full_static_mapping?.unique_signatures).toBe(27);
    expect(obs.coverage.timeloop_unresolved_shape_nodes).toBe(201);
    expect(obs.coverage.timeloop_unsupported_nodes).toBe(10693);
  });
  it('rejects unknown schema and mismatched source identity', () => {
    expect(() => validateGr00tObservation({ ...comparison, schema: 'veritx/unknown/1' })).toThrow(/schema/);
    expect(() => validateGr00tManifest({ ...manifest, reproduction: { ...manifest.reproduction, frame_index: 2 } }, validateGr00tObservation(comparison))).toThrow(/identities/);
  });
  it('rejects inconsistent graph counts, malformed hashes, and non-finite values', () => {
    const badGraph = structuredClone(comparison);
    badGraph.model_graphs.action_head.operator_counts.Add++;
    expect(() => validateGr00tObservation(badGraph)).toThrow(/reconcile/);
    const badHash = structuredClone(comparison);
    badHash.source.camera_sha256 = 'bad';
    expect(() => validateGr00tObservation(badHash)).toThrow(/identity/);
    const badNumber = structuredClone(comparison);
    badNumber.source.timestamp_s = Number.NaN;
    expect(() => validateGr00tObservation(badNumber)).toThrow(/identity/);
  });
  it('rejects inconsistent Timeloop mapped coverage', () => {
    const aggregateMismatch = structuredClone(comparison);
    aggregateMismatch.coverage.timeloop_mapped_nodes = 2;
    expect(() => validateGr00tObservation(aggregateMismatch)).toThrow(/coverage does not reconcile/);
    const graphOverflow = structuredClone(comparison);
    graphOverflow.model_graphs.action_head.timeloop_mapped_node_count = graphOverflow.model_graphs.action_head.node_count + 1;
    expect(() => validateGr00tObservation(graphOverflow)).toThrow(/Invalid graph or operator trace/);
  });
  it('rejects ROI provenance that does not identify a mapped graph operator', () => {
    const bad = structuredClone(comparison);
    bad.roi_simulation.graph_node_index = 301;
    expect(() => validateGr00tObservation(bad)).toThrow(/Invalid source-derived ROI/);
  });
  it('accepts the seven-preset same-trace topology comparison', () => {
    const obs = validateGr00tObservation(comparison);
    expect(obs.topology_sweep?.variants).toHaveLength(7);
    expect(obs.topology_sweep?.rankings_by_endpoint_count['64']).toHaveLength(6);
  });
  it('rejects a topology sweep bound to a different ROI trace', () => {
    const bad = structuredClone(comparison);
    bad.topology_sweep.trace_sha256 = '0'.repeat(64);
    expect(() => validateGr00tObservation(bad)).toThrow(/same-trace topology sweep/);
  });
  it('accepts the matched SROTA 8x8 comparison on the pinned ROI trace', () => {
    const obs = validateGr00tObservation(comparison);
    expect(obs.srota_comparison?.variants).toHaveLength(2);
    expect(obs.srota_comparison?.variants.find(v => v.name === 'srota_8x8')?.observed.request_latency_avg).toBe(26.991459074733097);
  });
  it('rejects SROTA results bound to another ROI trace', () => {
    const bad = structuredClone(comparison);
    bad.srota_comparison.trace_sha256 = '0'.repeat(64);
    expect(() => validateGr00tObservation(bad)).toThrow(/same-trace SROTA/);
  });
  it('rejects full-mapping node metrics that disagree with their signature', () => {
    const bad = structuredClone(comparison);
    const mapped = bad.model_graphs.action_head.operators.find(op => op.timeloop_mapping?.status === 'mapped')!;
    mapped.timeloop_mapping!.single_matrix_actual_computes = (mapped.timeloop_mapping!.single_matrix_actual_computes ?? 0) + 1;
    expect(() => validateGr00tObservation(bad)).toThrow(/Per-node Timeloop mapping/);
  });
  it('rejects ROI results that do not reconcile to the common BookSim trace', () => {
    const bad = structuredClone(comparison);
    bad.roi_simulation.booksim_variants[1].observed.flits++;
    expect(() => validateGr00tObservation(bad)).toThrow(/BookSim variants/);
  });
  it('rejects invalid architecture dimensions', () => {
    const badShape = structuredClone(comparison);
    badShape.model_graphs.action_head.inputs[0].shape = [-1, 77];
    expect(() => validateGr00tObservation(badShape)).toThrow(/graph or operator trace/);
  });
  it('refuses manifest graph hash mismatch', () => {
    const bad = structuredClone(manifest);
    bad.model_graphs.action_head = '0'.repeat(64);
    expect(() => validateGr00tManifest(bad, validateGr00tObservation(comparison))).toThrow(/does not match/);
  });
});
