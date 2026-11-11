import { useEffect, useState, type ReactNode } from 'react';
import { Assumptions, Badge, Field, Properties, Section } from './ui';
import { EvidencePlot } from './EvidencePlot';
import {
  dominatorsOf, formatMetric, genericFront, metricValue, seriesColor,
  type WorkbenchMetric, type WorkbenchObservation, type WorkbenchPreset,
  type WorkbenchState, type WorkbenchView,
} from './analysisWorkbench';

export type WorkbenchSource = { label: string; text: ReactNode; tone?: 'neutral' | 'blue' | 'amber' | 'red' };
type Mode = 'curve' | 'scatter' | 'bars';

const observationTone = (observation: WorkbenchObservation, frontIds: Set<string>, frontMode: WorkbenchView['frontMode']): 'neutral' | 'blue' | 'green' | 'amber' | 'red' => {
  if (observation.excluded) return 'amber';
  if (observation.tone) return observation.tone;
  if (frontMode !== 'none' && frontIds.has(observation.id)) return 'green';
  return 'neutral';
};
const observationWord = (observation: WorkbenchObservation, frontIds: Set<string>, frontMode: WorkbenchView['frontMode']): string => {
  if (observation.excluded) return 'Excluded';
  if (frontMode === 'none') return 'Measured';
  if (frontMode === 'authoritative') return frontIds.has(observation.id) ? 'Non-dominated' : 'Not on front';
  return frontIds.has(observation.id) ? 'Non-dominated' : 'Dominated';
};
const metricTitle = (metric: WorkbenchMetric): string => `${metric.label}${metric.unit ? ` (${metric.unit})` : ''}${metric.direction ? ` · ${metric.direction}` : ''}`;

export function AnalysisWorkbench({
  title, badges, source, actions, summary, context, notice, views, presets,
  defaultPreset, refine, tableSummary, table, after, assumptions, ownAssumptions = true, showBadges = true,
}: {
  title: string;
  badges?: ReactNode;
  source: WorkbenchSource;
  actions?: ReactNode | ((state: WorkbenchState) => ReactNode);
  summary?: ReactNode;
  context?: ReactNode | ((state: WorkbenchState) => ReactNode);
  notice?: ReactNode;
  views: WorkbenchView[];
  presets: WorkbenchPreset[];
  defaultPreset?: string;
  refine?: ReactNode;
  tableSummary?: string | ((state: WorkbenchState) => string);
  table?: ReactNode | ((state: WorkbenchState, select: (id: string) => void) => ReactNode);
  after?: ReactNode;
  assumptions?: [string, ReactNode][];
  ownAssumptions?: boolean;
  showBadges?: boolean;
}) {
  const firstPreset = presets.find(preset => preset.id === defaultPreset) ?? presets[0];
  const firstView = views.find(view => view.id === (firstPreset?.view ?? views[0]?.id)) ?? views[0];
  const [viewId, setViewId] = useState(firstView?.id ?? '');
  const [xKey, setXKey] = useState(firstPreset?.x ?? firstView?.defaultX ?? '');
  const [yKey, setYKey] = useState(firstPreset?.y ?? firstView?.defaultY ?? '');
  const [mode, setMode] = useState<Mode>(firstPreset?.mode ?? firstView?.mode ?? 'scatter');
  const [logY, setLogY] = useState(firstView?.defaultLogY ?? false);
  const [includeZero, setIncludeZero] = useState(false);
  const [frontOnly, setFrontOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const view = views.find(item => item.id === viewId) ?? views[0];
  const metrics = new Map((view?.metrics ?? []).map(metric => [metric.key, metric]));
  const metricKeys = (view?.metrics ?? []).map(metric => metric.key).join('|');
  const viewIds = views.map(item => item.id).join('|');
  const observationIds = (view?.observations ?? []).map(observation => observation.id).join('|');
  const activePreset = presets.find(preset => preset.view === view?.id && preset.x === xKey && preset.y === yKey
    && (preset.mode ?? view?.mode) === mode) ?? null;

  const applyPreset = (preset: WorkbenchPreset) => {
    const target = views.find(item => item.id === preset.view) ?? views[0];
    if (!target) return;
    setViewId(target.id);
    setXKey(preset.x);
    setYKey(preset.y);
    setMode(preset.mode ?? target.mode);
    setLogY(target.defaultLogY ?? false);
    setIncludeZero(false);
    setFrontOnly(false);
    setSelectedId(null);
    setHoveredId(null);
    setFilter('');
  };

  useEffect(() => {
    if (views.some(item => item.id === viewId)) return;
    const fallback = presets.find(preset => preset.id === defaultPreset) ?? presets[0];
    if (fallback) applyPreset(fallback);
    // viewIds is the stable identity of the view set.
  }, [viewIds, defaultPreset]);

  useEffect(() => {
    if (mode === 'bars') return;
    const keys = new Set((view?.metrics ?? []).map(metric => metric.key));
    if (xKey && !keys.has(xKey)) setXKey(view?.defaultX ?? '');
    if (yKey && !keys.has(yKey)) setYKey(view?.defaultY ?? '');
  }, [metricKeys, mode]);

  useEffect(() => {
    if (selectedId && !(view?.observations ?? []).some(observation => observation.id === selectedId)) setSelectedId(null);
    if (hoveredId && !(view?.observations ?? []).some(observation => observation.id === hoveredId)) setHoveredId(null);
  }, [observationIds, viewId]);

  if (!view) return null;
  const xMetric = metrics.get(xKey), yMetric = metrics.get(yKey);
  const visibleObservations = view.observations;
  const eligible = visibleObservations.filter(observation => !observation.excluded
    && metricValue(observation, yKey) !== null
    && (mode === 'bars' || metricValue(observation, xKey) !== null));
  const frontKeys = view.frontMode === 'generic' ? [xKey, yKey, ...(view.extraFrontKeys ?? [])] : [];
  const frontAvailable = view.frontMode === 'authoritative'
    || (view.frontMode === 'generic' && frontKeys.length > 0 && frontKeys.every(key => metrics.get(key)?.direction));
  const effectiveFrontMode = frontAvailable ? view.frontMode : 'none';
  const frontSet = view.frontMode === 'none' || !frontAvailable ? new Set<string>()
    : view.frontMode === 'authoritative' ? new Set(visibleObservations.filter(observation => observation.front && !observation.excluded).map(observation => observation.id))
    : new Set(genericFront(visibleObservations, metrics, frontKeys));
  const shown = frontOnly && effectiveFrontMode !== 'none'
    ? eligible.filter(observation => frontSet.has(observation.id))
    : eligible;
  const excluded = visibleObservations.filter(observation => observation.excluded).length;
  const selected = visibleObservations.find(observation => observation.id === selectedId);
  const preview = visibleObservations.find(observation => observation.id === hoveredId) ?? selected;
  const dominators = selected && effectiveFrontMode === 'generic' && !selected.excluded && !frontSet.has(selected.id)
    ? dominatorsOf(selected, visibleObservations, metrics, frontKeys, frontSet) : [];
  const dominator = dominators[0];
  const series = [...new Set(visibleObservations.flatMap(observation => observation.series ? [observation.series] : []))];
  const state: WorkbenchState = {
    viewId: view.id, xKey, yKey, mode, logY, includeZero, frontOnly,
    frontIds: [...frontSet], frontAvailable, plottedCount: shown.length, eligibleCount: eligible.length, selectedId,
  };
  const selectOptions = view.metricOptions ?? view.metrics;
  const hasAxisControls = mode !== 'bars' || selectOptions.length > 1;
  const hasScaleControls = mode !== 'bars';
  const hasControls = presets.length > 1 || hasAxisControls || hasScaleControls;
  const resolvedActions = typeof actions === 'function' ? actions(state) : actions;
  const resolvedContext = typeof context === 'function' ? context(state) : context;
  const resolvedTable = typeof table === 'function' ? table(state, setSelectedId) : table;
  const resolvedTableSummary = typeof tableSummary === 'function' ? tableSummary(state) : tableSummary ?? 'Observation data';
  const inspectorRows: [string, ReactNode][] = [];
  if (mode !== 'bars' && xMetric) inspectorRows.push([xMetric.label, formatMetric(xMetric, selected ? metricValue(selected, xKey) : null)]);
  if (yMetric) inspectorRows.push([yMetric.label, formatMetric(yMetric, selected ? metricValue(selected, yKey) : null)]);
  for (const key of view.inspectorKeys ?? []) {
    const metric = metrics.get(key);
    if (!metric || key === xKey || key === yKey) continue;
    inspectorRows.push([metric.label, formatMetric(metric, selected ? metricValue(selected, key) : null)]);
  }
  for (const [label, value] of selected?.meta ?? []) if (!inspectorRows.some(([existing]) => existing === label)) inspectorRows.push([label, value]);
  const pickerRows = view.picker === 'series'
    ? series.filter(name => !filter || name.toLowerCase().includes(filter.toLowerCase())).map(name => {
      const arm = visibleObservations.filter(observation => observation.series === name
        && metricValue(observation, mode === 'bars' ? yKey : xKey) !== null);
      const last = [...arm].sort((a, b) => (metricValue(a, mode === 'bars' ? yKey : xKey) ?? 0) - (metricValue(b, mode === 'bars' ? yKey : xKey) ?? 0)).slice(-1)[0];
      return { id: last?.id ?? name, label: name, sublabel: `${arm.length} points`, front: false, excluded: false, colour: seriesColor(name, series), disabled: false };
    })
    : visibleObservations
      .filter(observation => !filter || `${observation.label} ${observation.sublabel ?? ''}`.toLowerCase().includes(filter.toLowerCase()))
      .sort((a, b) => {
        if (mode === 'bars' && view.barSort === 'value') {
          const av = metricValue(a, yKey), bv = metricValue(b, yKey);
          if (av === null || bv === null) return av === null ? (bv === null ? a.label.localeCompare(b.label) : 1) : -1;
          return (av - bv) * (metrics.get(yKey)?.direction === 'MAX' ? -1 : 1) || a.label.localeCompare(b.label);
        }
        if (mode === 'bars') return 0;
        return Number(Boolean(b.front)) - Number(Boolean(a.front)) || Number(Boolean(a.excluded)) - Number(Boolean(b.excluded)) || a.label.localeCompare(b.label);
      })
      .map(observation => ({
        id: observation.id, label: observation.label, sublabel: observation.sublabel,
        front: frontSet.has(observation.id), excluded: Boolean(observation.excluded),
        colour: observation.excluded ? '#79540c'
          : mode === 'bars' && !view.barColorBySeries ? (frontSet.has(observation.id) ? '#246847' : '#9aabb8')
            : observation.series ? seriesColor(observation.series, series) : frontSet.has(observation.id) ? '#246847' : '#8a9aa8',
        disabled: frontOnly && effectiveFrontMode !== 'none' && !frontSet.has(observation.id),
      }));
  const badgeText = mode === 'curve'
    ? `${series.length} arms · ${shown.length} points`
    : effectiveFrontMode === 'none'
      ? `${shown.length} observation${shown.length === 1 ? '' : 's'}`
      : `${frontSet.size} non-dominated / ${eligible.length} ${view.eligibleLabel ?? 'eligible'}`;
  const xLabel = mode === 'curve' ? 'Horizontal axis' : 'Horizontal objective';
  const yLabel = mode === 'bars' ? 'Ranked objective' : mode === 'curve' ? 'Vertical axis' : 'Vertical objective';
  const hint = mode === 'curve'
    ? 'Hover a point for exact values. Click or press Enter to pin it and isolate its arm.'
    : mode === 'bars'
      ? 'Hover or focus a bar to inspect its exact values. Selecting does not change the source.'
      : 'Hover a point for exact values. Click or press Enter to pin its details.';

  return <Section title={title} actions={<>
    {badges}
    {showBadges && <Badge tone={source.tone ?? 'blue'}>{source.label}</Badge>}
    {showBadges && <Badge tone="blue">{badgeText}</Badge>}
    {excluded > 0 && <Badge tone="amber">{excluded} excluded</Badge>}
    {resolvedActions}
  </>}>
    {notice}
    {summary}
    {(hasControls || resolvedContext) && <div className="wb-controls">
      {resolvedContext}
      {presets.length > 1 && <div className="segmented wb-presets" role="group" aria-label="Plot view">
        {presets.map(preset => <button key={preset.id} type="button" className={activePreset?.id === preset.id ? 'active' : ''}
          aria-pressed={activePreset?.id === preset.id} title={preset.hint} onClick={() => applyPreset(preset)}>{preset.label}</button>)}
      </div>}
      {mode !== 'bars' && <Field label={xLabel}><select aria-label={xLabel} value={xKey} onChange={event => setXKey(event.target.value)}>
        {selectOptions.map(metric => <option key={metric.key} value={metric.key} disabled={Boolean((metric as { disabled?: boolean }).disabled) || metric.key === yKey}>{metricTitle(metric)}</option>)}
      </select></Field>}
      {(mode !== 'bars' || selectOptions.length > 1) && <Field label={yLabel}><select aria-label={yLabel} value={yKey} onChange={event => setYKey(event.target.value)}>
        {selectOptions.map(metric => <option key={metric.key} value={metric.key} disabled={Boolean((metric as { disabled?: boolean }).disabled) || (mode !== 'bars' && metric.key === xKey)}>{metricTitle(metric)}</option>)}
      </select></Field>}
      <div className="wb-scale">
        {mode !== 'bars' && <div className="segmented" role="group" aria-label="Plot scale">
          <button type="button" aria-pressed={!includeZero} className={!includeZero ? 'active' : ''} onClick={() => setIncludeZero(false)}>Fit data</button>
          <button type="button" aria-pressed={includeZero} className={includeZero ? 'active' : ''} onClick={() => setIncludeZero(true)}>Include zero</button>
        </div>}
        {mode !== 'bars' && <label className="check-row"><input type="checkbox" checked={logY} onChange={event => setLogY(event.target.checked)} />Log Y axis</label>}
        {effectiveFrontMode !== 'none' && mode !== 'curve' && <label className="check-row"><input type="checkbox" checked={frontOnly} onChange={event => setFrontOnly(event.target.checked)} />Front only</label>}
      </div>
    </div>}    {refine}
    <div className="plot-readout wb-readout" aria-live="polite" aria-atomic="true">
      {preview ? <>
        <strong>{preview.label}</strong>
        {preview.sublabel && <span>{preview.sublabel}</span>}
        {mode !== 'bars' && xMetric && <span><b>{xMetric.label}</b> {formatMetric(xMetric, metricValue(preview, xKey))}</span>}
        {yMetric && <span><b>{yMetric.label}</b> {formatMetric(yMetric, metricValue(preview, yKey))}</span>}
        <Badge tone={observationTone(preview, frontSet, effectiveFrontMode)}>{observationWord(preview, frontSet, effectiveFrontMode)}</Badge>
      </> : <span>{hint}</span>}
    </div>
    <div className="pareto-workbench wb-frame">
      <div className="pareto-canvas wb-canvas">
        {shown.length
          ? <EvidencePlot view={view} xKey={xKey} yKey={yKey} mode={mode} observations={shown} metrics={metrics}
            frontIds={frontSet} selectedId={selectedId} hoveredId={hoveredId}
            onHover={setHoveredId} onSelect={setSelectedId} onClear={() => setSelectedId(null)}
            includeZero={includeZero} logY={logY} title={view.chartTitle ?? title} />
          : <div className="wb-empty" role="status"><strong>{view.emptyMessage ?? 'No plottable observations at this selection.'}</strong>
            <p>{view.note ?? 'Missing values are never substituted. Clear a constraint or choose another view.'}</p></div>}
        <p className="plot-hint">
          {excluded > 0 ? `${excluded} excluded by status or constraint · ` : ''}
          {frontOnly ? 'front only · ' : ''}
          Actual observations, no interpolation.
          {view.note ? ` ${view.note}` : ''}
        </p>
      </div>
      <aside className="pareto-inspector wb-inspector" aria-label="Observation inspector">
        <div className="plot-inspector-heading"><h3>{selected?.label ?? 'No observation selected'}</h3>
          {selected && <Badge tone={observationTone(selected, frontSet, effectiveFrontMode)}>{observationWord(selected, frontSet, effectiveFrontMode)}</Badge>}</div>
        {selected ? <>
          {selected.sublabel && <p className="meta-line">{selected.sublabel}</p>}
          <Properties rows={inspectorRows} />
          {selected.excluded && <p className="meta-line">{selected.excluded}</p>}
          {dominator && <p className="meta-line">Dominated by <button className="text-button" onClick={() => setSelectedId(dominator.id)}>{dominator.label}</button>{dominators.length > 1 ? ` and ${dominators.length - 1} other${dominators.length > 2 ? 's' : ''}` : ''} on the selected objectives.</p>}
          {selected.note && <p className="meta-line">{selected.note}</p>}
          {view.frontMode === 'authoritative' && <p className="meta-line">Membership is decided by the source contract, not by the plotted axes. Inspecting an observation does not change it.</p>}
        </> : <p className="meta-line">Select a {mode === 'bars' ? 'bar' : 'point'} or a row to inspect exact values, exclusions and the comparison result.</p>}
        {view.picker !== 'none' && <>
          <h4>Inspect {view.picker === 'series' ? 'an arm' : 'an observation'} <span>{pickerRows.length}</span></h4>
          {pickerRows.length > 8 && <input className="wb-filter" aria-label={view.picker === 'series' ? 'Filter arms' : 'Filter observations'} placeholder={view.picker === 'series' ? 'Filter arms…' : 'Filter observations…'} value={filter} onChange={event => setFilter(event.target.value)} />}
          <div className="candidate-picker" role="group" aria-label={view.picker === 'series' ? 'Select an arm' : 'Select an observation'}>
            {pickerRows.map(row => <button key={row.id} type="button" aria-pressed={row.id === selectedId} disabled={row.disabled}
              className={`${row.front ? 'front' : ''} ${row.excluded ? 'excluded' : ''}`} onClick={() => row.id && setSelectedId(row.id)}>
              <i aria-hidden="true" style={{ background: row.colour }} />
              <span>{row.label}</span>
              <small>{row.excluded ? 'excluded' : row.front ? 'front' : view.picker === 'series' ? row.sublabel : effectiveFrontMode === 'none' ? row.sublabel ?? 'measured' : 'other'}</small>
            </button>)}
          </div>
        </>}
      </aside>
    </div>
    {resolvedTable && <details className="plot-data"><summary>{resolvedTableSummary}</summary>{resolvedTable}</details>}
    {after}
    {ownAssumptions && <Assumptions rows={[['Source', source.text], ...(assumptions ?? [])]} />}
  </Section>;
}
