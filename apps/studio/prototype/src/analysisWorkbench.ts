/** Shared vocabulary for the single analysis workbench.
 *
 *  Every evidence source (repository sweep, workload ablation, selected run,
 *  project study) supplies the same observation shape. The page owns the
 *  comparison mechanics; a source never gets a private chart, inspector or
 *  control set. Keeping the data model here also keeps front membership and
 *  requirement margins testable without React.
 */

export type MetricDirection = 'MIN' | 'MAX';

export type WorkbenchMetric = {
  key: string;
  label: string;
  unit?: string;
  direction?: MetricDirection;
  digits?: number;
};

export type WorkbenchObservation = {
  id: string;
  label: string;
  sublabel?: string;
  series?: string;
  values: Record<string, number | null | undefined>;
  /** Membership supplied by an authority (for example a study contract). */
  front?: boolean;
  /** Never plotted, never allowed into a derived front. */
  excluded?: string;
  tone?: 'green' | 'amber' | 'red' | 'neutral' | 'blue';
  meta?: [string, string][];
  note?: string;
};

export type WorkbenchView = {
  id: string;
  label: string;
  /** Accessible plot name; independent of the page/section title. */
  chartTitle?: string;
  metrics: WorkbenchMetric[];
  /** Options that stay visible but disabled when a source is not enabled. */
  metricOptions?: (WorkbenchMetric & { disabled?: boolean })[];
  observations: WorkbenchObservation[];
  mode: 'curve' | 'scatter' | 'bars';
  frontMode: 'generic' | 'authoritative' | 'none';
  /** Additional objectives that decide a generic front without being plotted. */
  extraFrontKeys?: string[];
  defaultX: string;
  defaultY: string;
  /** When x equals this key, curve observations are joined by series. */
  seriesAxis?: string;
  defaultLogY?: boolean;
  xLabel?: string;
  yLabel?: string;
  eligibleLabel?: string;
  note?: string;
  emptyMessage?: string;
  threshold?: { value: number; label: string };
  /** Bars are ordered by value, or kept in the source's declared order. */
  barSort?: 'value' | 'declared';
  /** Colour each bar by its observation series instead of the front/tone state. */
  barColorBySeries?: boolean;
  /** Use a log value axis for bars; useful when one arm is orders of magnitude larger. */
  barLog?: boolean;
  /** Curve mode shows one picker row per series, not one row per observation. */
  picker?: 'series' | 'observations' | 'none';
  /** Extra metric rows shown in the inspector after the plotted axes. */
  inspectorKeys?: string[];
};

export type WorkbenchPreset = {
  id: string;
  label: string;
  view: string;
  x: string;
  y: string;
  mode?: 'curve' | 'scatter' | 'bars';
  hint?: string;
};

export type WorkbenchState = {
  viewId: string;
  xKey: string;
  yKey: string;
  mode: 'curve' | 'scatter' | 'bars';
  logY: boolean;
  includeZero: boolean;
  frontOnly: boolean;
  frontAvailable: boolean;
  frontIds: string[];
  plottedCount: number;
  eligibleCount: number;
  selectedId: string | null;
};

export const SERIES_COLORS = ['#0f6c9e', '#a32928', '#246847', '#79540c', '#6b4f9e',
  '#0d7f7a', '#8a4b1f', '#3d5a80', '#9a2f6a', '#4b6a2f', '#5b5f66',
  '#1f6f8b', '#7a5c00'];

export const seriesColor = (series: string | undefined, all: string[]): string => {
  if (!series) return '#8a9aa8';
  const index = all.indexOf(series);
  return SERIES_COLORS[(index < 0 ? all.length : index) % SERIES_COLORS.length];
};

export const metricValue = (observation: WorkbenchObservation, key: string): number | null => {
  const value = observation.values[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
};

export const formatMetric = (metric: WorkbenchMetric | undefined, value: number | null | undefined): string => {
  if (!metric || typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const digits = metric.digits ?? 3;
  return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })}${metric.unit ? ` ${metric.unit}` : ''}`;
};

const dominates = (a: WorkbenchObservation, b: WorkbenchObservation, keys: string[], metrics: Map<string, WorkbenchMetric>): boolean => {
  let better = false;
  for (const key of keys) {
    const av = metricValue(a, key), bv = metricValue(b, key);
    if (av === null || bv === null) return false;
    const direction = metrics.get(key)?.direction;
    if (!direction) return false;
    if (direction === 'MIN') {
      if (av > bv) return false;
      if (av < bv) better = true;
    } else {
      if (av < bv) return false;
      if (av > bv) better = true;
    }
  }
  return better;
};

/** Non-dominated observations over the plotted axes plus any extra objectives.
 *  Missing values and excluded observations never enter or dominate a front. */
export function genericFront(
  observations: WorkbenchObservation[],
  metrics: Map<string, WorkbenchMetric>,
  keys: string[],
): string[] {
  const unique = [...new Set(keys)];
  if (!unique.length || unique.some(key => !metrics.get(key)?.direction)) return [];
  const eligible = observations.filter(observation => !observation.excluded
    && unique.every(key => metricValue(observation, key) !== null));
  return eligible.filter(observation => !eligible.some(other =>
    other !== observation && dominates(other, observation, unique, metrics))).map(observation => observation.id);
}

export function dominatorsOf(
  observation: WorkbenchObservation,
  observations: WorkbenchObservation[],
  metrics: Map<string, WorkbenchMetric>,
  keys: string[],
  frontIds: Set<string>,
): WorkbenchObservation[] {
  const unique = [...new Set(keys)];
  if (!unique.length || unique.some(key => !metrics.get(key)?.direction)) return [];
  return observations.filter(other => other !== observation && !other.excluded
      && dominates(other, observation, unique, metrics))
    .sort((a, b) => Number(frontIds.has(b.id)) - Number(frontIds.has(a.id)));
}

export type RequirementEntryLike = {
  traffic_class?: string;
  qos_class?: string;
  verdict?: string;
  required?: number | string | null;
  measured?: number | null;
  binding?: boolean;
  reason?: string | null;
  metric_authority?: string;
};

export type RequirementMargin = {
  direction: 'MAX_ALLOWED' | 'MIN_REQUIRED';
  ratio: number;
  /** Percentage of the requirement left (positive) or exceeded (negative). */
  headroomPercent: number;
};

/** The recorded reason or metric authority names the requirement direction.
 *  A requirement with no readable direction is listed, never guessed. */
export function requirementMargin(entry: RequirementEntryLike): RequirementMargin | null {
  if (typeof entry.measured !== 'number' || !Number.isFinite(entry.measured)) return null;
  if (typeof entry.required !== 'number' || !Number.isFinite(entry.required) || entry.required === 0) return null;
  const text = `${entry.reason ?? ''} ${entry.metric_authority ?? ''}`.toLowerCase();
  const ceiling = /<=|≤|ceiling|at most|no more than/.test(text);
  const floor = />=|≥|floor|at least|no less than/.test(text);
  const direction: RequirementMargin['direction'] | null = ceiling && !floor ? 'MAX_ALLOWED'
    : floor && !ceiling ? 'MIN_REQUIRED'
    : /bandwidth|throughput/.test(text) ? 'MIN_REQUIRED'
    : /latency|duration/.test(text) ? 'MAX_ALLOWED'
    : null;
  if (!direction) return null;
  const ratio = entry.measured / entry.required;
  return {
    direction,
    ratio,
    headroomPercent: (direction === 'MAX_ALLOWED' ? 1 - ratio : ratio - 1) * 100,
  };
}

export function verdictTone(verdict: string | undefined): 'green' | 'red' | 'amber' | 'neutral' {
  const text = String(verdict ?? '').toUpperCase();
  if (/SATISFIED|PASS|MET|WITHIN/.test(text)) return 'green';
  if (/VIOLATED|FAIL|BREACH|EXCEED/.test(text)) return 'red';
  if (!text) return 'neutral';
  return 'amber';
}
