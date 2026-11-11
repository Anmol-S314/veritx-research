export const projectId = 'p-rtl-delivery';
export const project = {
  project: { project_id: projectId, name: 'RTL delivery fixture', created_at: '2026-11-08T00:00:00Z', updated_at: '2026-11-08T00:00:00Z' },
  active_revision_id: `${projectId}-r01`,
  active_revision: { revision_id: `${projectId}-r01`, display_name: 'r01', design: { locked_derived: { vc_count: 2 }, noc_guided: { link_width: 64, topology_family: 'mesh' } } }, runs: [],
};
export const readiness = {
  revision_id: `${projectId}-r01`, draft_design_hash: 'sha256:fixture', final_rtl_available: false,
  final_rtl_reason: 'General router RTL realization is not connected.', preview_available: false,
  preview_blockers: ['Evaluate the finalized revision first.'], limitations: ['Existing emitter is a 64-bit, 2-VC preview.'],
};
export const longName = `${'mesh_router_'.repeat(8)}research_generated_verilog.v`;
function row(id: string, label: string, required: boolean, present = false, family: string | null = id) {
  return {
    topology_id: id, label, catalog_family: family, scope: 'RESEARCH_VERILOG', final_implementation: false,
    required, verilog_status: present ? 'PRESENT' : 'MISSING', verilog_file: present ? `${id}.v` : null,
    file_presence: present ? 'PRESENT' : 'UNKNOWN', generation_completeness: 'UNKNOWN', proof_status: 'UNVERIFIED',
    lint_status: 'NOT_RUN', simulation_status: 'NOT_RUN', source_reproduction_status: 'UNKNOWN', qualification_status: 'NOT_QUALIFIED',
    historical_snapshot: { reported_proof: 'historical report only', reported_verilog: 'reported emitted' }, lineage: 'UNKNOWN',
    artifacts: present ? [{ artifact_id: id, name: longName, size_bytes: 118, version: 'a'.repeat(64), download_url: `/catalog/rtl-prototypes/${id}/artifacts/${longName}?version=${'a'.repeat(64)}` }] : [],
    detail: 'Mutable research RTL; source lineage is unknown.',
  };
}
export const catalog = {
  contract_version: 2, scope: 'RESEARCH_VERILOG', final_implementation: false, provenance: 'fixture',
  counts: { required_total: 12, required_present: 1, required_missing_or_unknown: 11, optional_total: 1, non_target_total: 1 },
  prototypes: [row('mesh8x8', 'Mesh 8x8', true, true), ...['torus8x8', 'cmesh', 'fattree', 'flatfly', 'srota8x8', 'gec_mecs', 'gec_hybrid', 'qtree', 'tree4', 'ring', 'fly64'].map(id => row(id, id, true)), row('dragonflynew', 'DragonflyNew', false), row('kncube', 'KNCube', false, false, null)],
  artifacts: [],
};
