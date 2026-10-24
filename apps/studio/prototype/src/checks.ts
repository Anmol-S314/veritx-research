import { BASE_REVISION, DOMAIN_IDS, ROUTERS, overlaps, type Draft, type LocalFinding } from './model';

export function localChecks(draft: Draft): LocalFinding[] {
  const conflicts = overlaps(draft.regions);
  const invalidReference = draft.endpoints.some(e => !ROUTERS.includes(e.router) || !DOMAIN_IDS.includes(e.domain));
  const duplicate = new Set(draft.endpoints.map(e => e.id)).size !== draft.endpoints.length;
  const occupancyConflict = ROUTERS.some(router => {
    const members = draft.endpoints.filter(e => e.router === router);
    return members.length > 1 && (!members[0].concentrator || members.some(e => e.concentrator !== members[0].concentrator) || new Set(members.map(e => e.slot)).size !== members.length);
  });
  return [
    { id: 'LOCAL-ADDR-01', question: 'Declared address intervals do not overlap', outcome: conflicts.length ? 'Violated' : 'Pass', detail: conflicts.length ? `${conflicts.length} overlap(s) found by local interval arithmetic. This does not predict runtime decoder behavior.` : 'No overlaps in declared intervals. Runtime decoding and access enforcement are not checked.', page: 'design/addresses' },
    { id: 'LOCAL-REF-01', question: 'Endpoint identifiers and attachment references are consistent', outcome: invalidReference || duplicate || occupancyConflict ? 'Violated' : 'Pass', detail: 'Checks only this preview’s identifiers, declared router/domain references, Local-port occupancy, and explicit concentrator slots. Not protocol correctness.', page: 'design/endpoints' },
    { id: 'CDC-IMPL-01', question: 'Clock/reset crossing implementation is correct', outcome: 'Not evaluated', detail: 'No RTL, synchronizer model, CDC tool, or reset analysis is connected. Declaring domains cannot resolve this question.', page: 'design/domains' },
  ];
}
export function architecturePackage(draft: Draft, includeFixture: boolean) {
  return {
    schema: 'srota-studio-prototype/architecture-intent/v1',
    illustrative: true,
    project: 'Falcon8_NoC_Gen2',
    capturedDraft: structuredClone(draft),
    baselineReference: BASE_REVISION,
    topology: { family: 'Orthogonal 2D mesh', rows: 4, columns: 4, routerPorts: 'N/S/E/W/Local, boundary ports unused', linkBits: 128, clockMHz: 1400 },
    checks: localChecks(draft),
    suppliedDependencies: ['Memory controller and PHY implementation not supplied', 'Host interface implementation not supplied'],
    limitations: ['Descriptive local prototype export only', 'No RTL, bitstream, implementation constraints, physical library, or compute datapath generated', 'No backend evaluation, functional verification, formal proof, or ASIC/FPGA qualification'],
    fixtureReference: includeFixture ? { origin: 'Authored illustrative network-model data, not tool output', design: BASE_REVISION, workload: 'ResNet50_Burst [w12]', requirements: 'r5', run: 'SIM-402', transactionP95: 'Not recorded', historicalEvidenceDoesNotEvaluateCurrentDraft: true } : undefined,
  };
}
