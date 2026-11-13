import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { gateway, type CatalogAnalysis, type CatalogConfiguration, type CatalogRow, type NormalizedMetricValue } from './gateway';
import { catalogPerClassMetrics, configSummary, metricDimensions, rtlVerdict } from './catalogMetrics';
import { Badge, Button, Notice, Properties } from './ui';
import './catalogInspector.css';

export type CatalogInspectorProps = {
  row: CatalogRow | null;
  configuration: CatalogConfiguration | null;
  projectId: string;
  jobId: string;
  busy: string;
  acknowledge: boolean;
  onAcknowledge: (value: boolean) => void;
  onChoose: () => void;
  onClose: () => void;
  chosen: boolean;
  error: string;
  onRetry: () => void;
};

const tabs = ['Measurements', 'Configuration', 'Files'] as const;
type Tab = typeof tabs[number];
const valueText = (value: unknown): string => value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : typeof value === 'number' ? value.toLocaleString() : String(value);
const metricValue = (metric: NormalizedMetricValue) => `${valueText(metric.value)}${metric.unit ? ` ${metric.unit}` : ''}`;
const metricLabel = (key: string) => /^p\d+$/.test(key) ? key.toUpperCase() : key.replaceAll('_', ' ');
const statusTone = (status: string) => status === 'EVALUATED' || status === 'COMPLETED' ? 'green' : ['FAILED', 'EVIDENCE_INVALID'].includes(status) ? 'red' : 'amber';
const metricGroup = (key: string) => /^p\d+$/.test(key) ? 'percentile' : /packets|flits|bytes|transfers/.test(key) ? 'volume' : /cycles|latency|time|window|duration/.test(key) ? 'time' : 'other';
const groupLabel: Record<string, string> = { time: 'Timing', percentile: 'Latency percentiles', volume: 'Volume', other: 'Other recorded values' };

function MetricBars({ metrics, note = true }: { metrics: NormalizedMetricValue[]; note?: boolean }) {
  const groups = ['time', 'percentile', 'volume', 'other'].map(group => ({
    group,
    rows: metrics.filter(metric => metricGroup(metric.key) === group),
  })).filter(entry => entry.rows.length);
  return <div className="catalog-metric-groups" aria-label="Aggregate measurements">
    {groups.map(({ group, rows }) => {
      const max = Math.max(...rows.map(row => typeof row.value === 'number' ? Math.abs(row.value) : 0), 1);
      return <section className="catalog-metric-group" key={group}>
        <h4>{groupLabel[group]}</h4>
        {rows.map((metric, index) => <div className={`catalog-metric-row ${group}`} key={`${metric.key}:${index}`}>
          <span className="catalog-metric-label" title={metric.key}>{metricLabel(metric.key)}</span>
          {group !== 'other' && <span className="catalog-metric-track" aria-hidden="true"><i style={{ width: `${typeof metric.value === 'number' ? Math.max(2, Math.abs(metric.value) / max * 100) : 0}%` }} /></span>}
          <strong className="catalog-metric-value">{valueText(metric.value)}{metric.unit && metric.unit !== '—' ? <small> {metric.unit}</small> : null}</strong>
        </div>)}
      </section>;
    })}
    {note && <small className="catalog-metric-note">Bars compare values within this scope only; they are not a cross-scope score.</small>}
  </div>;
}

function ScopeMeasurements({ analysis, label }: { analysis?: CatalogAnalysis; label: string }) {
  const groups = catalogPerClassMetrics(analysis).sort((a, b) => a.trafficClass.localeCompare(b.trafficClass));
  const classRows = new Set(groups.flatMap(group => group.metrics));
  const classKeys = new Set(groups.flatMap(group => group.metrics.map(metric => metric.key)));
  const metrics = analysis?.normalized_metrics ?? [];
  const aggregate = metrics.filter(metric => !metric.dimensions?.length && !classRows.has(metric) && !classKeys.has(metric.key));
  const detailed = metrics.filter(metric => !!metric.dimensions?.length && !classRows.has(metric));
  const keys = [...new Set(groups.flatMap(group => group.metrics.map(metric => metric.key)))];
  return <section className="catalog-inspector-scope" aria-label={label}>
    <div className="catalog-inspector-section-heading"><h3 title={analysis?.backend_id ?? undefined}>{label}</h3><Badge tone={analysis ? statusTone(analysis.status) : 'neutral'}>{analysis?.status.replaceAll('_', ' ').toLowerCase() ?? 'Not started'}</Badge></div>
    {analysis?.reason && <p className="catalog-inspector-reason">{analysis.reason}</p>}
    {groups.length === 1 ? <div className="catalog-class-block">
      <h4>Per traffic class · {groups[0].trafficClass}</h4>
      <MetricBars metrics={groups[0].metrics} note={false} />
    </div> : groups.length > 1 && <div className="catalog-inspector-table-scroll" tabIndex={0} role="region" aria-label={`${label} per traffic class measurements`}>
      <table className="catalog-inspector-table catalog-inspector-pivot"><caption>Per traffic class · recorded values and units</caption><thead><tr><th scope="col">Metric</th>{groups.map(group => <th scope="col" key={group.trafficClass}>{group.trafficClass}</th>)}</tr></thead><tbody>
        {keys.map(key => <tr key={key}><th scope="row" title={key}>{metricLabel(key)}</th>{groups.map(group => {
          const recorded = group.metrics.filter(metric => metric.key === key);
          return <td key={group.trafficClass}>{recorded.length ? recorded.map((metric, index) => <span className="catalog-inspector-value" key={index}>{metricValue(metric)}</span>) : '—'}</td>;
        })}</tr>)}
      </tbody></table>
    </div>}
    {aggregate.length > 0 ? <MetricBars metrics={aggregate} /> : <p className="catalog-inspector-meta">No aggregate measurements recorded.</p>}
    {detailed.length > 0 && <section className="catalog-metric-group" aria-label={`${label} dimensioned measurements`}>
      <h4>Additional dimensions</h4>
      {detailed.map((metric, index) => <div className="catalog-metric-row other" key={`${metric.key}:${index}`}>
        <span className="catalog-metric-label" title={metric.key}>{metricLabel(metric.key)}<small className="catalog-inspector-dimensions">{metricDimensions(metric).map(([name, value]) => `${name}: ${value}`).join(' · ') || JSON.stringify(metric.dimensions)}</small></span>
        <strong className="catalog-metric-value">{valueText(metric.value)}{metric.unit && metric.unit !== '—' ? <small> {metric.unit}</small> : null}</strong>
      </div>)}
    </section>}
  </section>;
}

export function CatalogInspector({ row, configuration, projectId, jobId, busy, acknowledge, onAcknowledge, onChoose, onClose, chosen, error, onRetry }: CatalogInspectorProps) {
  const [tab, setTab] = useState<Tab>('Measurements');
  const heading = useRef<HTMLHeadingElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const prefix = useId();
  const identity = row ? `${row.topology_id}:${row.candidate_id ?? ''}` : '';
  useEffect(() => {
    setTab('Measurements');
    if (body.current) body.current.scrollTop = 0;
    if (identity) heading.current?.focus({ preventScroll: true });
  }, [identity]);
  useEffect(() => {
    if (error && body.current) body.current.scrollTop = 0;
  }, [error]);
  const changeTab = (next: Tab) => {
    setTab(next);
    if (body.current) body.current.scrollTop = 0;
  };
  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    changeTab(tabs[next]);
    tabRefs.current[next]?.focus({ preventScroll: true });
  };
  const rtl = row ? rtlVerdict(row.rtl_support) : null;
  const files = [...new Set(row?.trace_files ?? [])];
  const mismatch = row?.config?.matched === false || !!(row?.config?.controls_id && configuration?.controls_id && row.config.controls_id !== configuration.controls_id);
  const analyses = row?.analyses ?? [];
  return <aside className="catalog-inspector" id="catalog-fabric-detail" aria-label={row ? `${row.label} fabric details` : 'Fabric details'} tabIndex={-1}>
    <header className="catalog-inspector-header">
      <div><h2 ref={heading} tabIndex={-1}>{row?.label ?? 'Fabric details'}</h2>
        {row && <p className="catalog-inspector-meta">{row.fabric?.router_count == null ? 'Router count unavailable' : `${row.fabric.router_count} routers`} · {row.vc_count ?? row.fabric?.vc_count ?? 'Unavailable'} VCs{row.fabric?.shared_wire_links ? ` · ${row.fabric.shared_wire_links} shared wires` : ''}</p>}
      </div>{row && <Button onClick={onClose}>Close details</Button>}
    </header>
    {!row ? <div className="catalog-inspector-empty"><h3>Select a fabric to inspect</h3><p>Choose a fabric from the measured results or trade-off plot to review its measurements, configuration and generated files.</p></div> : <>
      <div className="catalog-inspector-tabs" role="tablist" aria-label="Fabric detail views">{tabs.map((name, index) => <button type="button" role="tab" id={`${prefix}-tab-${index}`} aria-controls={`${prefix}-panel-${index}`} aria-selected={tab === name} tabIndex={tab === name ? 0 : -1} ref={element => { tabRefs.current[index] = element; }} onClick={() => changeTab(name)} onKeyDown={event => handleTabKey(event, index)} key={name}>{name}{name === 'Files' ? ` (${files.length})` : ''}</button>)}</div>
      <div className="catalog-inspector-body" ref={body}>
        {error && <div className="catalog-inspector-error" role="alert"><p>{error}</p><Button onClick={onRetry} disabled={!!busy}>Retry status</Button></div>}
        <div className="catalog-inspector-verdict">
        <div className="catalog-inspector-status"><Badge tone={chosen ? 'green' : 'neutral'}>{chosen ? 'Chosen fabric' : 'Inspecting fabric'}</Badge><Badge tone={statusTone(row.status)}>{row.status.replaceAll('_', ' ').toLowerCase()}</Badge></div>
        <strong>{row.requirements_pass === true ? 'Declared requirements satisfied' : row.requirements_pass === false ? 'Declared requirements not satisfied' : 'Requirement verdict not established'}</strong>
        {row.reason && <p className="catalog-inspector-reason">{row.reason}</p>}
        {!row.selectable && <p className="catalog-inspector-reason">This fabric is not available for selection.</p>}
        {mismatch && <p className="catalog-inspector-warning">Configuration differs from the frozen catalog controls. These measurements are not directly comparable.</p>}
        {rtl && <p className="catalog-inspector-rtl" title={rtl.detail}>{rtl.text}</p>}
        </div>
        <section role="tabpanel" id={`${prefix}-panel-0`} aria-labelledby={`${prefix}-tab-0`} hidden={tab !== 'Measurements'} tabIndex={0}>
          <ScopeMeasurements label="BookSim · network" analysis={analyses.find(analysis => analysis.question === 'NETWORK_COMPLETION')} />
          <ScopeMeasurements label="ASTRA-SIM · system" analysis={analyses.find(analysis => analysis.question === 'SYSTEM_MAKESPAN')} />
          {analyses.filter(analysis => !['NETWORK_COMPLETION', 'SYSTEM_MAKESPAN'].includes(analysis.question)).map((analysis, index) => <ScopeMeasurements key={`${analysis.question}:${index}`} label={analysis.question} analysis={analysis} />)}
        </section>
        <section role="tabpanel" id={`${prefix}-panel-1`} aria-labelledby={`${prefix}-tab-1`} hidden={tab !== 'Configuration'} tabIndex={0}>
          <h3>Measured configuration</h3><p className="catalog-inspector-meta">{configSummary(row)}</p>
          <Properties rows={[
            ['Configuration match', mismatch ? 'Differs' : row.config?.matched === true ? 'Matched' : 'Not recorded'],
            ['Input buffer depth (flits/VC)', valueText(row.config?.input_buffer_depth_flits_per_vc)],
            ['Link width', valueText(row.config?.link_width)],
            ['Arbitration', valueText(row.config?.arbitration)],
            ['Routing class', valueText(row.fabric?.routing_class)],
            ['Measured VC count', valueText(row.vc_count ?? row.fabric?.vc_count)],
            ['Attempt', valueText(row.attempt)],
          ]} />
          <h3 className="catalog-inspector-subheading">RTL preview limits</h3><p>{rtl?.detail}</p>
          {row.rtl_support && <Properties rows={[
            ['Verdict code', row.rtl_support.code],
            ['Emitted VCs', valueText(row.rtl_support.emitted_vcs)],
            ['Measured VCs', valueText(row.rtl_support.vc_count)],
            ['Matches measured VCs', row.rtl_support.matches_certified_vc_count ? 'Yes' : 'No'],
          ]} />}
          {row.rtl_support && !row.rtl_support.matches_certified_vc_count && <Notice tone="amber"><strong>VC scheme mismatch.</strong> The preview emits {row.rtl_support.emitted_vcs} VCs; the measured design uses {valueText(row.rtl_support.vc_count)}. The preview is not simulation-equivalent for this fabric.</Notice>}
          <p className="catalog-inspector-meta">Topology-only preview; not final simulation-equivalent RTL or hardware qualification. Composed-family A1–A10 evidence is a separate tier and does not transfer to this row.</p>
        </section>
        <section role="tabpanel" id={`${prefix}-panel-2`} aria-labelledby={`${prefix}-tab-2`} hidden={tab !== 'Files'} tabIndex={0}>
          <h3>Generated input files</h3>
          {files.length ? <ul className="catalog-inspector-files">{files.map(file => <li key={file}><a href={gateway.catalogArtifactUrl(projectId, jobId, file)} title={file} download>{file.split('/').slice(-2).join('/')}</a></li>)}</ul> : <p>No generated input files recorded for this fabric.</p>}
        </section>
      </div>
      <footer className="catalog-inspector-footer">
        {!chosen && row.requires_backend_ack && <label className="catalog-inspector-ack"><input type="checkbox" checked={acknowledge} disabled={!!busy} onChange={event => onAcknowledge(event.target.checked)} />I understand that this fabric has incomplete backend coverage.</label>}
        {chosen ? <span className="catalog-inspector-chosen" role="status">Selected for refinement</span> : <Button primary disabled={!row.selectable || !!busy || (!!row.requires_backend_ack && !acknowledge)} onClick={onChoose}>{`Choose ${row.label}`}</Button>}
        {!!busy && <span className="catalog-inspector-meta" role="status">{busy === row.candidate_id ? 'Selecting fabric…' : 'Operation in progress…'}</span>}
      </footer>
    </>}
  </aside>;
}
