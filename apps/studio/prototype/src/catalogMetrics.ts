import type { CatalogAnalysis, CatalogRow, NormalizedMetricValue } from './gateway';

export function rtlVerdict(support: CatalogRow['rtl_support']): { tone: 'green' | 'red' | 'amber'; text: string; detail: string } {
  if (!support) return { tone: 'amber', text: 'RTL not recorded', detail: 'This catalog job ran before RTL feasibility was recorded. Run the catalog again to predict it.' };
  if (support.supported) {
    const mismatch = support.vc_count != null && support.vc_count !== support.emitted_vcs;
    return {
      tone: 'amber',
      text: `Preview · ${support.emitted_vcs} VC${support.emitted_vcs === 1 ? '' : 's'}${mismatch ? ` (measured ${support.vc_count})` : ''}`,
      detail: `Topology-only preview from the product emitter; not final RTL, simulation equivalence or hardware qualification.${mismatch ? ` The preview emits ${support.emitted_vcs} VCs while the measured design uses ${support.vc_count}; the VC scheme is not equivalent.` : ''}`,
    };
  }
  return { tone: 'red', text: 'No RTL preview', detail: support.reason ?? 'The product RTL emitter cannot serve this fabric.' };
}

/** M5 research-Verilog evidence for one catalog row (v2 contract).
 *  Speaks only in PRESENT/MISSING file presence; never READY/qualified. */
export function researchRtlVerdict(research: CatalogRow['research_rtl']): { tone: 'green' | 'red' | 'amber' | 'neutral'; text: string; detail: string } {
  if (!research) return { tone: 'neutral', text: 'No M5 entry', detail: 'No M5 research RTL entry recorded for this catalog row. Research Verilog only, not product-final RTL.' };
  const snapshot = research.historical_snapshot;
  const snapshotNote = snapshot
    ? `Historical snapshot: ${snapshot.reported_verilog}; reported proof ${snapshot.reported_proof}.`
    : 'Historical snapshot not recorded.';
  const detail = `Proof status: ${research.proof_status}. ${snapshotNote} Research Verilog only, not product-final RTL.`;
  if (research.verilog_status === 'PRESENT') return { tone: 'green', text: 'Research Verilog present', detail };
  if (research.verilog_status === 'MISSING') return { tone: research.required ? 'red' : 'amber', text: 'No Verilog file', detail };
  return { tone: 'amber', text: 'Research Verilog status unknown', detail };
}

export function configSummary(row: CatalogRow): string {
  const buffer = row.config?.input_buffer_depth_flits_per_vc;
  const routing = row.fabric?.routing_class ?? 'routing not recorded';
  return `${buffer === null || buffer === undefined ? 'buffer: default' : `${buffer} flits/VC`} · ${routing}`;
}

export function metricDimensions(metric: NormalizedMetricValue): [string, string][] {
  const out: [string, string][] = [];
  for (const entry of metric.dimensions ?? []) {
    if (Array.isArray(entry) && entry.length >= 2 && typeof entry[0] === 'string' && (typeof entry[1] === 'string' || typeof entry[1] === 'number')) out.push([entry[0], String(entry[1])]);
    else if (entry && typeof entry === 'object') {
      const row = entry as Record<string, unknown>;
      const name = row.name ?? row.dimension;
      const value = row.value;
      if (typeof name === 'string' && (typeof value === 'string' || typeof value === 'number')) out.push([name, String(value)]);
    }
  }
  return out;
}

export function catalogPerClassMetrics(analysis?: CatalogAnalysis): { trafficClass: string; metrics: NormalizedMetricValue[] }[] {
  const groups = new Map<string, NormalizedMetricValue[]>();
  for (const metric of analysis?.normalized_metrics ?? []) {
    const dimensions = metricDimensions(metric);
    if (dimensions.length !== 1 || dimensions[0][0] !== 'traffic_class') continue;
    const trafficClass = dimensions[0][1];
    if (!trafficClass) continue;
    const rows = groups.get(trafficClass) ?? [];
    rows.push(metric);
    groups.set(trafficClass, rows);
  }
  return [...groups].map(([trafficClass, metrics]) => ({ trafficClass, metrics }));
}
