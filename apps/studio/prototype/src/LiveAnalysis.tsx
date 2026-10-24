import { useEffect, useState } from 'react';
import { EvidenceDocuments } from './EvidenceDocuments';
import { RawArtifacts } from './RawArtifacts';
import { useGatewayDocument } from './LiveOperations';
import { useLoadedProject, useLoadedRun, useProject } from './project';
import type { LoadedProject, LoadedRun } from './project';
import { gateway, gatewayReason, type RunDetail } from './gateway';
import { Badge, Empty, Inspector, Notice, PageLink, Properties, Section } from './ui';
import { LaunchEvaluation } from './LaunchEvaluation';

const short = (value?: string | null, keep = 20) => value ? `${value.slice(0, keep)}…` : 'Not supplied';
const num = (value: number | null | undefined, unit = '') => value === null || value === undefined ? '—' : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}${unit}`;

export function LiveGate({ children }: { children: (project: LoadedProject, run: LoadedRun) => React.ReactNode }) {
  const { run: runState, loadRun } = useProject();
  const project = useLoadedProject();
  const run = useLoadedRun();
  if (!project) return <div className="view-main"><Empty title="No project loaded">Load a project from <a href="#/shared/projects">Projects &amp; revisions</a> to read its evaluations from the gateway.</Empty></div>;
  if (!run) {
    const runs = project.detail.runs ?? [];
    return <div className="view-main">
      <Notice tone="amber"><strong>{project.detail.project.name}: no evaluation selected.</strong> {runs.length ? 'Pick a run below.' : 'This project has no runs.'}</Notice>
      {runState.phase === 'loading' && <p>Loading run {runState.runId} …</p>}
      {runState.phase === 'error' && <Notice tone="red">{runState.reason}</Notice>}
      {runs.length > 0 && <Section title="Runs in this project"><div className="table-scroll"><table><thead><tr><th>Run</th><th>Revision</th><th>Status</th><th>Backend</th><th>Action</th></tr></thead><tbody>
        {runs.map(r => <tr key={r.run_id}><th className="mono">{r.run_id.slice(0, 13)}…<br /><small>{r.display_name ?? ''}</small></th><td className="mono">{r.revision_id}</td><td><Badge tone={r.status === 'EVALUATED' ? 'green' : r.status === 'FAILED' ? 'red' : 'amber'}>{r.status}</Badge></td><td className="mono">{r.backend ?? '—'}</td><td><button className="button" onClick={() => loadRun(r.run_id)}>Inspect</button></td></tr>)}
      </tbody></table></div></Section>}
      <LaunchEvaluation project={project} />
    </div>;
  }
  return <>{children(project, run)}</>;
}

export function RunBar({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const { loadRun } = useProject();
  const runs = project.detail.runs ?? [];
  return <div className="toolbar">
    <select aria-label="Selected run" value={run.detail.run_id} onChange={e => loadRun(e.target.value)}>
      {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 13)} · {r.revision_id} · {r.status}</option>)}
    </select>
    <Badge tone={run.detail.status === 'EVALUATED' ? 'green' : run.detail.status === 'FAILED' ? 'red' : 'amber'}>{run.detail.status}</Badge>
    <Badge>{run.detail.qualification ?? 'Qualification not declared'}</Badge>
    <Badge tone={run.detail.requirements_pass === true ? 'green' : run.detail.requirements_pass === false ? 'red' : 'amber'}>Requirements {run.detail.requirements_pass === true ? 'pass' : run.detail.requirements_pass === false ? 'fail' : 'not evaluated'}</Badge>
    {project.draftMeta?.dirty && <Badge tone="amber">Uncompiled draft changes · run uses saved revision</Badge>}
    <span className="mono muted">{run.detail.revision_id}</span>
  </div>;
}

function RunBanner({ run }: { run: LoadedRun }) {
  return <Notice tone="blue"><strong>Run {run.detail.run_id.slice(0, 13)}…</strong> · {run.detail.backend ?? 'backend not declared'} · {run.detail.revision_id}. Reported by this bundle.</Notice>;
}

function Gap({ label }: { label: string }) {
  return <Badge tone="amber">{label}</Badge>;
}

export function LiveAnalysisSummary({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const d = run.detail;
  const metrics = d.evaluation?.metrics ?? {};
  const entries = d.requirements?.entries ?? [];
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <RunBanner run={run} />
    <LaunchEvaluation project={project} />
    {d.evaluation?.fidelity_warning && <Notice tone="amber"><strong>Fidelity:</strong> {d.evaluation.fidelity_warning}</Notice>}
    {!d.evaluation && <Notice tone="amber"><strong>No evaluation block:</strong> status {d.status}, bundle {short(d.bundle_id)}.</Notice>}
    <Section title="Evaluation outcome" actions={<Badge tone={d.status === 'EVALUATED' ? 'green' : 'amber'}>{d.status}</Badge>}>
      <Properties rows={[[ 'Backend', d.backend ?? 'Not declared' ], ['Qualification', d.qualification ?? 'Not declared' ], ['Qualification basis', d.qualification_basis ?? 'Not declared' ], ['Revision', d.revision_id ], ['Design hash', <span className="mono">{short(d.design_hash)}</span> ], ['Resolved fabric hash', <span className="mono">{short(d.evaluation?.resolved_fabric_hash)}</span> ], ['Completion cycles', num(metrics.completion_cycles) ], ['Sample window (cycles)', num(metrics.sample_window_cycles) ], ['Wall time (ns)', num(d.evaluation?.network_traffic_window?.wall_time_ns) ], ['Started / completed', `${d.started_at ?? '—'} → ${d.completed_at ?? '—'}` ]]} />
    </Section>
    <Section title="Requirement verdicts" actions={<Badge>{entries.length} declared</Badge>}>
      {entries.length ? <div className="table-scroll"><table><thead><tr><th>Requirement</th><th>Class / QoS</th><th>Verdict</th><th>Measured</th><th>Required</th><th>Metric authority</th></tr></thead><tbody>
        {entries.map((entry, i) => <tr key={`${entry.requirement_index ?? i}`}>
          <th className="mono">REQ-{entry.requirement_index ?? i + 1}</th>
          <td>{entry.traffic_class ?? '—'} / {entry.qos_class ?? '—'}</td>
          <td><Badge tone={/PASS|MET|SATISFIED/i.test(String(entry.verdict)) ? 'green' : /FAIL|VIOLAT/i.test(String(entry.verdict)) ? 'red' : 'amber'}>{entry.verdict ?? 'Not evaluated'}</Badge></td>
          <td className="numeric">{num(entry.measured)}</td>
          <td className="numeric">{entry.required === null || entry.required === undefined ? '—' : String(entry.required)}</td>
          <td><small>{entry.metric_authority ?? 'Not supplied'}</small></td>
        </tr>)}
      </tbody></table></div> : <Empty title="No requirement verdicts in this run">The evaluation reports no requirement entries. Nothing is inferred.</Empty>}
      {entries.some(e => e.reason) && <div className="stack">{entries.filter(e => e.reason).map((e, i) => <p key={i}><strong>REQ-{e.requirement_index ?? i + 1}:</strong> {e.reason}</p>)}</div>}
    </Section>
    <Section title="Analyses in this run">
      {[d.analyses ?? []].flat().length ? <div className="table-scroll"><table><thead><tr><th>Backend</th><th>Status</th><th>Fidelity</th><th>Limitations</th></tr></thead><tbody>
        {(d.analyses ?? []).map((a, i) => <tr key={`${a.backend_id}-${i}`}><th className="mono">{a.backend_id ?? '—'}</th><td><Badge tone={a.status === 'EVALUATED' ? 'green' : 'amber'}>{a.status ?? '—'}</Badge></td><td>{a.model_fidelity ?? '—'}</td><td>{(a.limitations ?? []).join('; ') || 'None declared'}</td></tr>)}
      </tbody></table></div> : <Empty title="No analysis records">The run reports no backend analyses.</Empty>}
    </Section>
{run.gaps.length > 0 && <Section title="Partial reads"><p>These gateway reads failed and are shown as absent rather than estimated:</p><ul>{run.gaps.map(g => <li key={g}>{g}</li>)}</ul></Section>}
  </div><Inspector title="Evaluation scope">
    <Properties rows={[[ 'Run', <span className="mono">{short(d.run_id, 24)}</span> ], ['Project', project.detail.project.name ], ['Evidence id', <span className="mono">{short(d.evidence?.evidence_id)}</span> ], ['Bundle id', <span className="mono">{short(d.bundle_id)}</span> ], ['Raw evidence digest', <span className="mono">{short(d.evaluation?.evidence?.raw_evidence_digest)}</span> ], ['Failure reason', d.reason ?? 'None; the run produced evidence' ]]} />
    <PageLink page="analysis/matrix">Inspect traffic matrix</PageLink>
    <PageLink page="analysis/metrics">Inspect metrics</PageLink>
    <PageLink page="verify/evidence">Inspect evidence bundle</PageLink>
  </Inspector></div>;
}

const METRIC_ORDER = ['completion_cycles', 'sample_window_cycles', 'delivered_packets', 'flits_injected', 'flits_accepted', 'injected_trace_packets', 'loaded_trace_packets', 'packet_latency_avg', 'flit_latency_avg'];

export function LiveMetrics({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const metrics = run.detail.evaluation?.metrics ?? {};
  const keys = [...METRIC_ORDER.filter(k => metrics[k] !== undefined), ...Object.keys(metrics).filter(k => !METRIC_ORDER.includes(k))];
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <RunBanner run={run} />
    <Section title="Reported metrics" actions={<Badge>{keys.length} values</Badge>}>
      {keys.length ? <div className="table-scroll"><table><thead><tr><th>Metric</th><th>Value</th><th>Reporting analysis</th><th>Distribution</th></tr></thead><tbody>
        {keys.map(k => <tr key={k}><th className="mono">{k}</th><td className="numeric">{num(metrics[k])}</td><td>{(run.detail.analyses ?? []).map(a => a.backend_id).join(', ') || 'Not declared'}</td><td><Gap label="No histogram or percentiles supplied" /></td></tr>)}
      </tbody></table></div> : <Empty title="No metrics reported">This evaluation produced no metric block.</Empty>}
    </Section>
    <Section title="What is not claimed">
      <Properties rows={[[ 'Latency definition', 'Backend-reported averages only; no percentile or distribution' ], ['Transaction completion', 'Not measured; packet averages are not transaction P95' ], ['Power / area / timing', 'Not evaluated' ], ['Cross-run comparison', 'Requires the same workload and revision window' ], ['Analyses limitations', (run.detail.analyses ?? []).flatMap(a => a.limitations ?? []).join('; ') || 'None declared' ]]} />
    </Section>
  </div><Inspector title="Metric origin">
    <Properties rows={[[ 'Source', 'run.evaluation.metrics' ], ['Backend', run.detail.backend ?? 'not declared' ], ['Window', run.detail.evaluation?.network_traffic_window ? `${num(run.detail.evaluation.network_traffic_window.window_cycles)} cycles` : 'Not declared' ], ['Evidence digest', <span className="mono">{short(run.detail.evaluation?.evidence?.stats_digest)}</span> ]]} />
    <PageLink page="analysis/summary">Back to evaluation summary</PageLink>
  </Inspector></div>;
}

export function LiveMatrix({ project, run, variant }: { project: LoadedProject; run: LoadedRun; variant?: 'missing' }) {
  const [basis, setBasis] = useState<'packets' | 'flits'>('packets');
  const [pair, setPair] = useState<string>('');
  const matrix = run.matrix;
  if (!matrix) return <div className="view-main"><RunBar project={project} run={run} /><Notice tone="amber"><strong>No traffic matrix.</strong> {run.gaps.find(g => g.startsWith('traffic matrix')) ?? ''}</Notice></div>;
  const grid = (basis === 'packets' ? matrix.matrix : matrix.flit_matrix) ?? [];
  const max = Math.max(1, ...grid.flat());
  const pairs = matrix.pairs ?? [];
  const selected = pairs.find(p => `${p.src}:${p.dst}` === pair) ?? pairs[0];
  const cell = (value: number) => value === 0 ? '#f7f9fb' : `rgba(15,108,158,${0.08 + 0.62 * (value / max)})`;
  const capped = grid.length > 24;
  const shown = capped ? grid.slice(0, 24).map(row => row.slice(0, 24)) : grid;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <RunBanner run={run} />
    <div className="toolbar">
      <select aria-label="Matrix basis" value={basis} onChange={e => setBasis(e.target.value as typeof basis)}><option value="packets">Packets</option><option value="flits">Flits</option></select>
      <Badge>{matrix.availability}</Badge>
      <Badge>{matrix.nodes} nodes</Badge>
      <Badge>{num(matrix.pairs?.length ?? matrix.distinct_pairs)} distinct pairs</Badge>
    </div>
    {variant === 'missing' && <Notice tone="amber"><strong>Fixture scenario, real data:</strong> availability {matrix.availability}.</Notice>}
    <Notice tone="blue"><strong>{matrix.availability}</strong> counts from <code>{matrix.source?.trace ?? 'the bundle'}</code>. Zero cells are recorded zeros.</Notice>
    <Section title={`${basis === 'packets' ? 'Packet' : 'Flit'} count by source → destination`} actions={<Badge>max {num(max)}</Badge>}>
      {grid.length ? <>
        <div className="table-scroll"><table className="live-matrix"><thead><tr><th>src \\ dst</th>{shown[0].map((_, j) => <th key={j} className="mono">{j}</th>)}</tr></thead><tbody>
          {shown.map((row, i) => <tr key={i}><th className="mono">{i}</th>{row.map((value, j) => <td key={j}><button className={`matrix-cell${selected && selected.src === i && selected.dst === j ? ' matrix-selected' : ''}`} style={{ background: cell(value) }} onClick={() => setPair(`${i}:${j}`)} aria-label={`Inspect ${i} to ${j}`}>{value === 0 ? '0' : num(value)}</button></td>)}</tr>)}
        </tbody></table></div>
        {capped && <p>Showing the first 24 of {grid.length} nodes to keep the grid readable. The pair list below carries every reported pair.</p>}
        <div className="legend"><span>Scale 0–{num(max)}</span><span>{matrix.classes ? `Classes: ${Object.entries(matrix.classes).map(([k, v]) => `${k} → ${v}`).join(', ')}` : 'No class split reported'}</span><span>Zero is a recorded zero, not missing</span></div>
      </> : <Empty title="The matrix document holds no grid">The run reports availability {matrix.availability} without a node grid.</Empty>}
    </Section>
    <Section title={`Endpoint pairs · ${pairs.length}`}>
      {pairs.length ? <div className="table-scroll"><table><thead><tr><th>Source</th><th>Destination</th><th>Packets</th><th>Flits</th></tr></thead><tbody>
        {pairs.map(p => <tr key={`${p.src}:${p.dst}`} className={selected && p.src === selected.src && p.dst === selected.dst ? 'selected' : ''}><td className="mono">{p.src}</td><td className="mono">{p.dst}</td><td className="numeric">{num(p.packets)}</td><td className="numeric">{num(p.flits)}</td></tr>)}
      </tbody></table></div> : <Empty title="No pair rows">Counts exist only in the grid.</Empty>}
    </Section>
  </div><Inspector title="Selected pair">
    {selected ? <><h3 className="mono">{selected.src} → {selected.dst}</h3><Properties rows={[[ 'Packets', num(selected.packets) ], ['Flits', num(selected.flits) ], ['Share of delivered packets', matrix.packets ? `${(100 * selected.packets / matrix.packets).toFixed(2)} %` : '—' ], ['Observed route', 'Not supplied by this document' ], ['Latency for this pair', <Gap label="Not reported" /> ], ['Traffic class', matrix.classes ? Object.keys(matrix.classes).join(', ') : 'Not declared' ]]} /></> : <p>Select a cell or pair.</p>}
    <Properties rows={[[ 'Availability', matrix.availability ], ['Source trace', matrix.source?.trace ?? 'Not declared' ], ['Declared packets', num(matrix.source?.declared_packets) ], ['Delivered packets', num(matrix.packets) ], ['Delivered flits', num(matrix.flits) ]]} />
    <PageLink page="analysis/metrics">Inspect reported metrics</PageLink>
  </Inspector></div>;
}

export function LiveAnalysisTopology({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const topology = project.topology;
  const channels = topology?.channels ?? [];
  const widths = [...new Set(channels.map(c => c.width_bits))].sort((a, b) => a - b);
  const latencies = [...new Set(channels.map(c => c.latency_cycles))].sort((a, b) => a - b);
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <Notice tone="amber"><strong>No per-link counters in this run</strong> — declared link properties only.</Notice>
    <Section title="Declared directed channels" actions={<Badge>{channels.length} channels</Badge>}>
      {channels.length ? <div className="table-scroll"><table><thead><tr><th>Channel</th><th>From</th><th>To</th><th>Width (bits)</th><th>Latency (cycles)</th></tr></thead><tbody>
        {channels.slice(0, 96).map((c, i) => <tr key={`${c.src_router}-${c.src_port}-${c.dst_router}-${i}`}><th className="mono">CH-{i + 1}</th><td className="mono">{c.src_router}:{c.src_port}</td><td className="mono">{c.dst_router}:{c.dst_port}</td><td className="numeric">{c.width_bits}</td><td className="numeric">{c.latency_cycles}</td></tr>)}
      </tbody></table></div> : <Empty title="No channels declared">The revision topology carries no channel list.</Empty>}
      {channels.length > 96 && <p>Showing 96 of {channels.length} channels.</p>}
    </Section>
    <Section title="Where per-link traffic would come from">
      <Properties rows={[[ 'Reported by this run', 'Endpoint-pair packets/flits, aggregate completion cycles' ], ['Missing for a link overlay', 'Per-directed-link flit counts and busy cycles' ], ['Substitution policy', 'None; derived utilization is not shown' ], ['Link widths declared', widths.length ? `${widths.join(', ')} bits` : 'Not declared' ], ['Link latencies declared', latencies.length ? `${latencies.join(', ')} cycles` : 'Not declared' ], ['Topology family', topology?.family ?? 'Not supplied' ]]} />
    </Section>
  </div><Inspector title="Overlay boundary">
    <Properties rows={[[ 'Source', 'GET /api/v1/revisions/{id}/topology' ], ['Run evaluated revision', run.detail.revision_id ], ['Current revision', project.detail.active_revision_id ?? '—' ], ['Same revision', project.detail.active_revision_id === run.detail.revision_id ? 'Yes' : 'No' ], ['Utilization overlay', <Gap label="Not available" /> ]]} />
    <PageLink page="analysis/matrix">Inspect endpoint-pair counts</PageLink>
  </Inspector></div>;
}

export function LiveTrace({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const files = run.artifacts?.bundle?.files ?? {};
  const traceFiles = Object.keys(files).filter(path => /\.trace$|trace\/|(^|\/)routing\.dump$/.test(path));
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <Notice tone="amber"><strong>Requested injections and realized first hops only.</strong> Decode a verified injection schedule or first-hop realization table below; observed packet-hop traces are not recorded.</Notice>
    <RawArtifacts key={run.detail.run_id} runId={run.detail.run_id} files={files} tracesOnly />
    <Section title="Trace artefacts in the bundle" actions={<Badge>{traceFiles.length} matching entries</Badge>}>
      {traceFiles.length ? <div className="table-scroll"><table><thead><tr><th>Path</th><th>sha256</th><th>Size</th></tr></thead><tbody>
        {traceFiles.map(path => <tr key={path}><td className="mono">{path}</td><td className="mono">{short(files[path], 24)}</td><td className="numeric">See evidence document</td></tr>)}
      </tbody></table></div> : <Empty title="No trace artefact in this bundle">The bundle lists {Object.keys(files).length} files and none is a trace. A packet trace cannot be reconstructed from aggregate counts.</Empty>}
    </Section>
    <Section title="Traffic volume reported instead">
      <Properties rows={[[ 'Declared packets (workload)', num(run.matrix?.source?.declared_packets ?? run.detail.evaluation?.metrics?.injected_trace_packets) ], ['Loaded packets', num(run.detail.evaluation?.metrics?.loaded_trace_packets) ], ['Delivered packets', num(run.detail.evaluation?.metrics?.delivered_packets) ], ['Flits injected / accepted', `${num(run.detail.evaluation?.metrics?.flits_injected)} / ${num(run.detail.evaluation?.metrics?.flits_accepted)}` ], ['Per-packet timing', <Gap label="Not supplied" /> ]]} />
    </Section>
  </div><Inspector title="Trace boundary">
    <Properties rows={[[ 'Bundle', <span className="mono">{short(run.detail.bundle_id)}</span> ], ['Files in bundle', String(run.artifacts?.bundle?.file_count ?? Object.keys(files).length) ], ['Trace decoding', 'Injection schedule + first-hop realization tables; never a full packet path' ], ['Synthetic trace', 'Never generated' ]]} />
    <PageLink page="verify/evidence">Inspect the evidence bundle</PageLink>
  </Inspector></div>;
}

export function LiveComparison({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const others = (project.detail.runs ?? []).filter(r => r.run_id !== run.detail.run_id);
  const [otherId, setOtherId] = useState(others[0]?.run_id ?? '');
  const [other, setOther] = useState<{ phase: 'idle' | 'loading' | 'loaded' | 'error'; detail?: RunDetail; reason?: string }>({ phase: 'idle' });
  useEffect(() => {
    if (!otherId) return;
    let live = true;
    setOther({ phase: 'loading' });
    gateway.run(otherId).then(detail => { if (live) setOther({ phase: 'loaded', detail }); })
      .catch(error => { if (live) setOther({ phase: 'error', reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, [otherId]);
  const backend = useGatewayDocument(
    `comparison:${run.detail.run_id}:${other.detail?.run_id ?? 'none'}`,
    () => other.detail ? gateway.compare(run.detail.run_id, other.detail.run_id) : Promise.resolve({} as Record<string, any>),
  );
  const backendRows = (backend.data?.rows ?? []) as any[];
  const compatibility = (backend.data?.compatibility ?? {}) as Record<string, any>;
  const definitionIssues = (compatibility.metric_definition_issues ?? []) as any[];
  const definitionTone = (verdict: string) => verdict === 'COMPARABLE' ? 'green' as const : verdict === 'DEFINITION_DIFFERENCE' ? 'red' as const : 'amber' as const;
  const verdictNote = !other.detail ? null : !backend.data
    ? (backend.error ? `Backend comparison unavailable: ${backend.error}` : 'Reading backend comparison…')
    : compatibility.compatible
      ? 'Backend verdict: COMPARABLE. Deltas below are server-computed; no statistical significance is claimed.'
      : `Backend verdict: not comparable. ${(compatibility.reasons ?? []).join('; ') || 'See per-row verdicts.'}`;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <div className="toolbar">
      <label className="field"><span>Compare against</span>
        <select aria-label="Comparison run" value={otherId} onChange={e => setOtherId(e.target.value)}>
          {others.length === 0 && <option value="">No other run in this project</option>}
          {others.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 13)} · {r.revision_id} · {r.status}</option>)}
        </select>
      </label>
      {other.phase === 'loading' && <Badge tone="amber">Reading run…</Badge>}
      {other.phase === 'error' && <Badge tone="red">{other.reason}</Badge>}
    </div>
    {verdictNote && <Notice tone={compatibility.compatible ? 'blue' : 'amber'}>{verdictNote}</Notice>}
    <Section title="Reported metrics side by side · backend verdicts">
      {other.detail && backendRows.length ? <div className="table-scroll"><table><thead><tr><th>Metric</th><th>Definition</th><th>A · {run.detail.run_id.slice(0, 13)}…</th><th>B · {otherId.slice(0, 13)}…</th><th>Δ (B − A)</th><th>Verdict</th><th>Reason</th></tr></thead><tbody>
        {backendRows.map((row: any, i: number) => <tr key={`${row.question ?? ''}:${row.key ?? '?'}:${i}`}>
          <th className="mono">{row.question ? `${row.question} · ` : ''}{row.key ?? '—'}{row.dimensions ? ` · ${row.dimensions}` : ''}</th>
          <td className="mono">{row.definition_id ?? row.unit ?? '—'}</td>
          <td className="numeric">{num(row.a)}</td><td className="numeric">{num(row.b)}</td>
          <td className="numeric">{row.comparable && typeof row.delta_b_minus_a === 'number' && Number.isFinite(row.delta_b_minus_a) ? num(row.delta_b_minus_a) : '—'}</td>
          <td><Badge tone={definitionTone(row.verdict)}>{row.verdict ?? '—'}</Badge>{row.differs ? <><br /><small className="mono">{row.differs}</small></> : null}</td>
          <td><small>{row.reason ?? '—'}</small></td>
        </tr>)}
      </tbody></table></div> : other.phase === 'error' ? <Empty title="Second run unavailable">{other.reason}</Empty> : !other.detail ? <Empty title="Nothing to compare">Pick a second run; this project has {others.length}.</Empty> : backend.error ? <Notice tone="amber">Backend comparison unavailable: {backend.error}</Notice> : <p>Reading backend comparison…</p>}
    </Section>
    {other.detail && <Section title="Compatibility gate · server-computed">
      {!backend.data ? (backend.error ? <Notice tone="amber">Backend comparison unavailable: {backend.error}</Notice> : <p>Reading backend comparison…</p>) : <>
        <Properties rows={[
          ['Backend compatible', compatibility.compatible ? 'Yes' : 'No'],
          ['Same workload', String(compatibility.same_workload ?? '—')],
          ['Same backend', String(compatibility.same_backend ?? '—')],
          ['Qualified evidence chain', String(compatibility.both_qualified ?? '—')],
          ['Backend configuration', `${compatibility.backend_configuration_state ?? '—'} · A ${short(compatibility.a_backend_config_hash, 12)} / B ${short(compatibility.b_backend_config_hash, 12)}`],
          ['Measurement window', `${compatibility.measurement_window_state ?? '—'} · A ${compatibility.a_measurement_window_cycles ?? '—'} / B ${compatibility.b_measurement_window_cycles ?? '—'} cycles`],
          ['Metric definitions complete', String(compatibility.metric_definitions_complete ?? '—')],
          ['Metadata complete', String(compatibility.metadata_complete ?? '—')],
          ...((compatibility.metadata_warnings ?? []) as string[]).map((w: string, i: number) => [`Warning ${i + 1}`, w] as [string, string]),
        ]} />
        {definitionIssues.length > 0 && <div className="stack">{definitionIssues.map((issue: any, i: number) => <Notice key={i} tone="red"><strong>{issue.metric}:</strong> {issue.detail ?? issue.issue}</Notice>)}</div>}
        {backend.data.note && <p>{backend.data.note}</p>}
      </>}
    </Section>}
    <Section title="Reading this comparison">
      <Properties rows={[[ 'Run A', `${run.detail.run_id.slice(0, 13)}… · ${run.detail.revision_id} · ${run.detail.backend ?? '—'}` ], ['Run B', other.detail ? `${other.detail.run_id.slice(0, 13)}… · ${other.detail.revision_id} · ${other.detail.backend ?? '—'}` : 'Not selected' ], ['Authority', 'GET /api/v1/compare — the browser performs no gating arithmetic' ], ['Requirement verdicts', 'Evaluated per run, on each run summary' ], ['Statistical significance', 'Not claimed' ], ['Confidence intervals', <Badge tone="amber">Not supplied</Badge> ]]} />
    </Section>
  </div><Inspector title="Runs in project">
    <ol className="activity-list">{(project.detail.runs ?? []).map(r => <li key={r.run_id}><span className="mono">{r.run_id.slice(0, 13)}…</span> · {r.revision_id} · {r.status}{r.run_id === run.detail.run_id ? ' · A' : r.run_id === otherId ? ' · B' : ''}</li>)}</ol>
    <PageLink page="analysis/summary">Evaluation summary</PageLink>
  </Inspector></div>;
}

export function LiveEvidence({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const files = run.artifacts?.bundle?.files ?? {};
  const total = Object.values(files).length;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <RunBanner run={run} />
    <Section title="Evidence identity">
      <Properties rows={[[ 'Run', <span className="mono">{run.detail.run_id}</span> ], ['Evidence id', <span className="mono">{run.detail.evidence?.evidence_id ?? '—'}</span> ], ['Raw evidence digest', <span className="mono">{run.detail.evaluation?.evidence?.raw_evidence_digest ?? '—'}</span> ], ['Stats digest', <span className="mono">{run.detail.evaluation?.evidence?.stats_digest ?? '—'}</span> ], ['Bundle id', <span className="mono">{run.detail.bundle_id ?? '—'}</span> ], ['Bundle digest algorithm', run.artifacts?.bundle?.algorithm ?? '—' ], ['Files', String(run.artifacts?.bundle?.file_count ?? total) ], ['Qualification', `${run.detail.qualification ?? '—'} · ${run.detail.qualification_basis ?? 'no basis declared'}` ], ['Design / resolved fabric', `${short(run.detail.design_hash)} / ${short(run.detail.evaluation?.resolved_fabric_hash)}` ]]} />
    </Section>
    <EvidenceDocuments key={run.detail.run_id} runId={run.detail.run_id} />
    <RawArtifacts key={`raw-${run.detail.run_id}`} runId={run.detail.run_id} files={files} />
    <Section title="Bundle files with recorded digests" actions={<Badge>{total} listed</Badge>}>
      {total ? <div className="table-scroll"><table><thead><tr><th>Path</th><th>sha256</th></tr></thead><tbody>
        {Object.entries(files).map(([path, digest]) => <tr key={path}><td className="mono">{path}</td><td className="mono">{digest}</td></tr>)}
      </tbody></table></div> : <Empty title="No file digests returned">The artifacts endpoint returned no bundle files for this run.</Empty>}
    </Section>
    {run.gaps.length > 0 && <Notice tone="amber">Partial reads: {run.gaps.join(' · ')}</Notice>}
  </div><Inspector title="Claim scope">
    <Properties rows={[[ 'Evidence origin', 'Repository gateway run bundle' ], ['Computed by this prototype', 'Nothing; values are displayed as reported' ], ['Integrity verification', 'See Local Checks' ], ['Transaction-level latency', 'Not measured' ], ['Hardware qualification', 'Not established by a network simulation' ]]} />
    <PageLink page="verify/checks">Inspect conservation and route realization</PageLink>
    <PageLink page="analysis/metrics">Inspect metrics</PageLink>
  </Inspector></div>;
}

export function LiveChecks({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const integrity = run.integrity;
  const rows = [
    ['Packet conservation', integrity?.packet_conservation],
    ['Flit conservation', integrity?.flit_conservation],
  ] as const;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    {!integrity && <Notice tone="amber"><strong>No integrity document.</strong> {run.gaps.find(g => g.startsWith('integrity')) ?? ''}</Notice>}
    {integrity && <>
      <Notice tone="blue"><strong>Backend-reported.</strong> <code>NOT_AVAILABLE</code> means undeclared, not zero.</Notice>
      <Section title="Conservation">
        <div className="table-scroll"><table><thead><tr><th>Quantity</th><th>Stage</th><th>Value</th><th>Availability</th></tr></thead><tbody>
          {rows.flatMap(([label, block]) => Object.entries(block ?? {}).map(([stage, value]) => {
            if (typeof value === 'string') return <tr key={`${label}-${stage}`} className="selected"><th>{label}</th><td>backend verdict</td><td className="numeric">{value}</td><td><Badge tone={/CONSERVED|PASS/i.test(value) ? 'green' : 'amber'}>reported</Badge></td></tr>;
            const entry = value as { value: number | null; availability: string };
            return <tr key={`${label}-${stage}`}><th>{label}</th><td>{stage}</td><td className="numeric">{num(entry?.value)}</td><td><Badge tone={entry?.availability === 'MEASURED' ? 'green' : 'amber'}>{entry?.availability ?? '—'}</Badge></td></tr>;
          }))}
        </tbody></table></div>
      </Section>
      <Section title="Route realization">
        <Properties rows={[[ 'Status', integrity.route_realization?.status ?? '—' ], ['Scope', integrity.route_realization?.scope ?? '—' ], ['Full path claimed', integrity.route_realization?.full_path_claimed ? 'Yes' : 'No' ], ['Realized digest', <span className="mono">{short(integrity.route_realization?.realized_digest)}</span> ], ['Evidence id', <span className="mono">{short(integrity.evidence_id)}</span> ]]} />
      </Section>
      <Section title="Per-analysis status">
        <div className="table-scroll"><table><thead><tr><th>Analysis</th><th>Backend</th><th>Status</th><th>Packets / flits</th></tr></thead><tbody>
          {Object.entries(integrity.analyses ?? {}).map(([name, value]) => <tr key={name}><th className="mono">{name}</th><td>{value.backend ?? '—'}</td><td><Badge tone={value.status === 'EVALUATED' ? 'green' : 'amber'}>{value.status ?? '—'}</Badge></td><td className="numeric">{num(value.packets)} / {num(value.flits)}</td></tr>)}
        </tbody></table></div>
      </Section>
    </>}
  </div><Inspector title="Check scope">
    <Properties rows={[[ 'Source', 'GET /api/v1/runs/{run_id}/integrity' ], ['Conservation', 'Backend-reported, per-stage availability' ], ['Deadlock proof', 'Not supplied' ], ['Functional correctness', 'Not evaluated' ], ['Prototype computation', 'None' ]]} />
    <PageLink page="verify/evidence">Inspect evidence bundle</PageLink>
  </Inspector></div>;
}

export function LiveRunArtifacts({ run }: { run: LoadedRun }) {
  const bundle = run.artifacts?.bundle;
  const files = bundle?.files ?? {};
  const entries = Object.entries(files);
  return <>
    <EvidenceDocuments key={run.detail.run_id} runId={run.detail.run_id} />
    <RawArtifacts key={`raw-${run.detail.run_id}`} runId={run.detail.run_id} files={files} />
    <Properties rows={[[ 'Run', <span className="mono">{run.detail.run_id.slice(0, 13)}…</span> ], ['Bundle id', <span className="mono">{bundle?.bundle_id ? `sha256:${bundle.bundle_id}` : short(run.detail.bundle_id)}</span> ], ['Algorithm', bundle?.algorithm ?? '—' ], ['File count', String(bundle?.file_count ?? entries.length) ], ['Endpoint', 'GET /api/v1/runs/{run_id}/artifacts' ], ['Files shown here', `${entries.length} recorded, ${Object.keys(files).length ? 'real digests' : 'none'}` ]]} />
    {entries.length ? <div className="table-scroll"><table><thead><tr><th>Artifact</th><th>sha256</th></tr></thead><tbody>
      {entries.map(([path, digest]) => <tr key={path}><td className="mono">{path}</td><td className="mono">{digest}</td></tr>)}
    </tbody></table></div> : <Empty title="No artifact digests for this run">The artifacts endpoint returned no file map.</Empty>}
  </>;
}
