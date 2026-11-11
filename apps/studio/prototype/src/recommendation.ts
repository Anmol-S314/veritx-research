import type { OptimizationStudyCandidate } from './gateway';

/** Families the certified patcher can substitute for this base. It converts
 * only between mesh / concentrated_mesh / torus (candidate._apply_v4_patch);
 * the executable list alone is design-independent, so it cannot be trusted. */
export const CONVERTIBLE_FAMILIES = ['mesh', 'concentrated_mesh', 'torus'];

/** Deterministic shortlist, not a performance prediction. The backend still
 * validates each family against the immutable workload and endpoint demand. */
export function fabricComparisonFamilies(executable: string[], current?: string, typedTopology = false): string[] {
  if (typedTopology && !CONVERTIBLE_FAMILIES.includes(String(current).toLowerCase())) return [];
  const families = [...new Set(executable)].filter(family => family && (!typedTopology || CONVERTIBLE_FAMILIES.includes(family.toLowerCase())));
  const baseline = families.find(family => family.toLowerCase() === current?.toLowerCase());
  return [...(baseline ? [baseline] : []), ...families.filter(family => family !== baseline)].slice(0, 4);
}

export type FabricDomain = { name: string; values: (number | string)[] }[];
export type FabricParameter = { name: string; kind: string; executable?: boolean; qualified_for_certified_optimization?: boolean; executable_values?: string[] | null };

/** Four-point local grid. No workload, routing, or VC mutations. A declared
 * baseline is mandatory; unsupported typed-family conversions are excluded. */
export function discoverFabricDomain(parameters: FabricParameter[], request: Record<string, any>): FabricDomain {
  const qualified = parameters.filter(p => p.executable === true && p.qualified_for_certified_optimization === true);
  const topology = request.topology;
  const controls = topology ? request.noc_controls ?? {} : request.noc_config ?? {};
  const current = topology?.kind ?? controls.topology_family;
  const family = qualified.find(p => p.name === 'topology_family');
  const compatible = CONVERTIBLE_FAMILIES;
  const families = fabricComparisonFamilies((family?.executable_values ?? []).filter(value => !topology || (compatible.includes(current) && compatible.includes(value))), current);
  const baselineFamily = families.find(value => value.toLowerCase() === current?.toLowerCase());
  const axes: FabricDomain = [];
  if (baselineFamily && families.length > 1) axes.push({ name: 'topology_family', values: families.slice(0, 2) });
  for (const name of ['link_width', 'concentration', 'radix']) {
    if (axes.length === 2) break;
    if (!qualified.some(p => p.name === name && p.kind === 'int')) continue;
    const radixField: Record<string, string> = { mesh: 'side_length', concentrated_mesh: 'side_length', torus: 'side_length', flatfly: 'radix_per_dimension', fattree: 'switch_radix', gec: 'grid_side_length' };
    const value = topology && name !== 'link_width' ? topology[name === 'radix' ? radixField[current] : name] : controls[name];
    const alternative = name === 'link_width' ? value * 2 : value + 1;
    if (!Number.isSafeInteger(value) || value < 1 || !Number.isSafeInteger(alternative)) continue;
    axes.push({ name, values: [value, alternative] });
  }
  return axes.length === 2 ? axes : [];
}

export function fabricGrid(domain: FabricDomain): Record<string, number | string>[] {
  return domain.reduce<Record<string, number | string>[]>((rows, axis) => rows.flatMap(row => axis.values.map(value => ({ ...row, [axis.name]: value }))), [{}]);
}

/** Why a study produced no recommendation, from the candidates themselves. */
export function recommendationGap(candidates: OptimizationStudyCandidate[], metric: string): string {
  if (!candidates.length) return 'The study returned no candidates.';
  const measured = candidates.filter(c => c.evaluation_status === 'EVALUATED' && c.objective_availability?.[metric] === 'MEASURED');
  if (measured.length) {
    const unmet = measured.filter(c => c.product_requirements?.satisfied === false).length;
    if (unmet === measured.length) return `All ${measured.length} measured configurations violate a binding product requirement, so none can be recommended. Their measurements remain evidence of what ran.`;
    return `${measured.length} of ${candidates.length} configurations carry a measured ${metric}, but none passes every declared constraint. Inspect the verdicts below.`;
  }
  const refused = candidates.filter(c => c.compilation_status && !['COMPILED', 'SUCCEEDED'].includes(String(c.compilation_status))).length;
  if (refused) return `${refused} of ${candidates.length} configurations were refused before evaluation; a refusal is not a zero-valued result.`;
  return `No configuration produced a measured ${metric}.`;
}

/** Stable C1…Cn labels, ordered by the first declared domain value so every
 * surface names the same candidate the same way. The content hash stays the
 * identity; it is not a readable label. */
export function candidateNames(study: { definition?: any; study?: { definition?: any; candidates?: OptimizationStudyCandidate[] } }): Map<string, string> {
  const definition = study.definition ?? study.study?.definition;
  const domain = definition?.domain;
  const params = Array.isArray(domain) ? domain : Object.entries(domain ?? {}).map(([name, values]) => ({ name, values }));
  const first = params[0]?.name;
  const sorted = [...(study.study?.candidates ?? [])].sort((a, b) => {
    const av = first ? a.guided_patch?.[first] : undefined;
    const bv = first ? b.guided_patch?.[first] : undefined;
    if (typeof av === 'number' && typeof bv === 'number') return av - bv;
    return String(av ?? '').localeCompare(String(bv ?? ''));
  });
  return new Map(sorted.map((candidate, index) => [candidate.candidate_id, `C${index + 1}`]));
}

/** Content-addressed identity, shortened for display only. */
export function shortDigest(id: string): string {
  const hex = id.replace(/^[a-z]+_/, '');
  return hex.length > 16 ? `${hex.slice(0, 8)}…${hex.slice(-6)}` : hex;
}

export function rankMeasured(candidates: OptimizationStudyCandidate[], metric: string, direction: string, constraints: string[]) {
  return candidates.filter(candidate => candidate.evaluation_status === 'EVALUATED'
    && candidate.evaluation_authority === 'certified-backend'
    && candidate.pareto_eligible === true
    && candidate.objective_availability?.[metric] === 'MEASURED'
    && typeof candidate.objective_values?.[metric] === 'number'
    && Number.isFinite(candidate.objective_values[metric])
    && constraints.every(key => candidate.constraint_verdicts?.[key] === 'SATISFIED'))
    .sort((a, b) => (direction === 'MAX' ? -1 : 1) * (a.objective_values![metric] - b.objective_values![metric]));
}
