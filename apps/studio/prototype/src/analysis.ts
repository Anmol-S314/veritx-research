import { candidateById, makeDraft, routeBetween } from './model';
export const NETWORK_CYCLES = 450000;
export const NETWORK_CLOCK_MHZ = 1400;
export const WINDOW_SECONDS = NETWORK_CYCLES / (NETWORK_CLOCK_MHZ * 1e6);
export const ANALYSIS_RUNS = [
  { id: 'SIM-402', candidate: 'BASE', workload: 'ResNet50_Burst [w12]', comparable: true, scope: 'Phase 2 · 450,000 cycles · 1.4 GHz' },
  { id: 'SIM-451', candidate: 'C-09', workload: 'ResNet50_Burst [w12]', comparable: true, scope: 'Phase 2 · 450,000 cycles · 1.4 GHz' },
  { id: 'SIM-401', candidate: null, workload: 'Uniform synthetic [w11]', comparable: false, scope: 'Whole run · different workload and window' },
] as const;
export type AnalysisRunId = typeof ANALYSIS_RUNS[number]['id'];
export function analysisObservation(id: AnalysisRunId) {
  const run = ANALYSIS_RUNS.find(r => r.id === id)!;
  const c = run.candidate ? candidateById(run.candidate) : null;
  return { ...run, latency: c?.latency ?? 20.2, throughput: c?.throughput ?? 18.7 };
}
export const MATRIX_SOURCES = ['EP_NPU_0', 'EP_NPU_1', 'EP_NPU_2', 'EP_NPU_3', 'EP_HOST', 'EP_DMA'];
export const MATRIX_TARGETS = ['EP_HBM_0', 'EP_HBM_1'];
const delivery = [[60000, 20000], [30000, 58000], [20000, 0], [16000, 24000], [16000, 12000], [28000, 45464]];
export const PAIR_FIXTURE = MATRIX_SOURCES.flatMap((source, i) => MATRIX_TARGETS.map((target, j) => ({ source, target, deliveredFlits: delivery[i][j], injectedFlits: delivery[i][j] + 100, requestedFlits: Math.round(delivery[i][j] * 1.15) + 200 })));
export function flitsGBps(flits: number) { return flits * 16 / WINDOW_SECONDS / 1e9; }
export function linkObservations() {
  const endpoints = makeDraft().endpoints;
  const values = new Map<string, { from: string; to: string; flits: number }>();
  for (const pair of PAIR_FIXTURE) {
    const path = routeBetween(endpoints.find(e => e.id === pair.source)!.router, endpoints.find(e => e.id === pair.target)!.router);
    for (let i = 1; i < path.length; i++) { const from = path[i - 1], to = path[i], key = `${from}:${to}`; const prior = values.get(key); values.set(key, { from, to, flits: (prior?.flits ?? 0) + pair.deliveredFlits }); }
  }
  return [...values.values()].map(l => ({ ...l, percent: l.flits / NETWORK_CYCLES * 100 })).sort((a, b) => b.flits - a.flits);
}
export const TRACE_DEMO = [
  { id: 'DEMO-001', cycle: 100000, event: 'INJECT', router: 'R_1_2', packet: 'DEMO-PKT-A', detail: 'Authored example injection event; not captured in SIM-402.' },
  { id: 'DEMO-002', cycle: 100001, event: 'HOP', router: 'R_1_1', packet: 'DEMO-PKT-A', detail: 'One adjacent column-first mesh hop.' },
  { id: 'DEMO-003', cycle: 100002, event: 'HOP', router: 'R_1_0', packet: 'DEMO-PKT-A', detail: 'Second adjacent mesh hop.' },
  { id: 'DEMO-004', cycle: 100003, event: 'EJECT', router: 'R_0_0', packet: 'DEMO-PKT-A', detail: 'Example event sequence ends here; no complete transaction is modeled.' },
];
