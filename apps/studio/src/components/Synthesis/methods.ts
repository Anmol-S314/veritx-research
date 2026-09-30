
export const ROUTES = {
  synthesize: (projectId: string): string =>
    `/projects/${projectId}/synthesize`,
  candidates: (projectId: string): string =>
    `/projects/${projectId}/candidates`,
  candidateDetail: (projectId: string, candidateId: string): string =>
    `/projects/${projectId}/candidates/${encodeURIComponent(candidateId)}`,
} as const;

export type CompletenessKind = 'EXHAUSTIVE' | 'BUDGETED' | 'UNBOUNDED';

export interface ParamField {
  name: string;
  label: string;
  kind: 'int' | 'float' | 'select' | 'text';
  def: number | string;
  min?: number;
  max?: number;
  options?: (string | number)[];
  help: string;
}

export interface SynthesisMethod {
  id: 'milp' | 'sa' | 'bo' | 'rho' | 'grpo';
  label: string;
  tagline: string;
  claim: string;
  completeness: CompletenessKind;
  completenessNote: string;
  engine: string;
  solverStatus: string;
  cli: string[] | null;
  cliNote: string;
  adapter?: string;
  params: ParamField[];
}

export const METHODS: SynthesisMethod[] = [
  {
    id: 'milp',
    label: 'Exact MILP / TMCF',
    tagline: 'Exact formulation within the declared formulation and solve status.',
    claim: 'OPTIMAL only when the solver proves it. A TIME_LIMIT incumbent is a feasible proposal, never an optimum.',
    completeness: 'BUDGETED',
    completenessNote: 'Exact over the declared MILP formulation up to the node cap and timeout — never global topology optimality.',
    engine: 'milp_tmcf',
    solverStatus: 'OPTIMAL or TIME_LIMIT (honest solver status preserved)',
    cli: null,
    cliNote: 'No CLI verb yet — run via the canonical adapter veritx_dse.synthesis.candidate.synthesize() (Python API); the candidate lands in Candidates.',
    adapter: 'veritx_dse.synthesis.candidate.synthesize (exact TMCF ≤ max_nodes, SA branch above; .anynet is a projection, never authority)',
    params: [
      { name: 'nodes', label: 'Node count', kind: 'int', def: 16, min: 2, max: 256, help: 'Router count. Exact solve caps at max_nodes; above it the SA path runs.' },
      { name: 'k', label: 'Grid side k', kind: 'int', def: 4, min: 2, help: 'Grid layout requires nodes == k×k.' },
      { name: 'radix', label: 'Maximum degree / radix', kind: 'int', def: 4, min: 2, help: 'Per-router link budget.' },
      { name: 'max_len', label: 'Maximum link length', kind: 'float', def: 2.0, min: 0.5, help: 'Layout-pitch admissibility radius.' },
      { name: 'timeout_s', label: 'Solver timeout (s)', kind: 'int', def: 120, min: 1, help: 'Execution policy, not problem identity.' },
      { name: 'max_nodes', label: 'Maximum exact-solve nodes', kind: 'int', def: 20, min: 2, help: 'Above this the SA heuristic runs (recorded as provenance).' },
      { name: 'objective', label: 'Generator objective', kind: 'select', def: 'geodesic', options: ['geodesic', 'priced_geodesic'], help: 'Analytical generator objective — never measured performance.' },
    ],
  },
  {
    id: 'sa',
    label: 'Simulated Annealing',
    tagline: 'Heuristic. No global optimality claim.',
    claim: 'Best observed among evaluated candidates. FEASIBLE always, OPTIMAL never.',
    completeness: 'UNBOUNDED',
    completenessNote: 'Heuristic graph search — no claim of global optimality.',
    engine: 'milp_tmcf',
    solverStatus: 'FEASIBLE (SA branch provenance)',
    cli: null,
    cliNote: 'No CLI verb yet — run via the canonical adapter (SA branch above max_nodes); the candidate lands in Candidates.',
    params: [
      { name: 'nodes', label: 'Node count', kind: 'int', def: 64, min: 2, help: 'Router count.' },
      { name: 'k', label: 'Grid side k', kind: 'int', def: 8, min: 2, help: 'Grid layout requires nodes == k×k.' },
      { name: 'radix', label: 'Maximum degree / radix', kind: 'int', def: 4, min: 2, help: 'Per-router link budget.' },
      { name: 'max_len', label: 'Maximum link length', kind: 'float', def: 2.0, min: 0.5, help: 'Layout-pitch admissibility radius.' },
      { name: 'seed', label: 'Seed', kind: 'int', def: 7, min: 0, help: 'Deterministic runs require an explicit seed.' },
    ],
  },
  {
    id: 'bo',
    label: 'Bayesian optimization',
    tagline: 'Surrogate-guided parameterized topology exploration.',
    claim: 'BUDGETED over the declared generator space. The default surrogate is honestly labelled seeded-random — a GP returns only with a vendored, qualified surrogate.',
    completeness: 'BUDGETED',
    completenessNote: 'Budgeted over cluster/express/radix/weight dimensions — never exhaustive, never globally optimal.',
    engine: 'bo_gp',
    solverStatus: 'FEASIBLE',
    cli: ['veritx', 'synthesize', 'bo'],
    cliNote: 'CLI verb exists. Scorer analytical (default) or booksim.',
    adapter: 'veritx_dse.synthesis.bo_adapter (generate_topology + run_bo → to_topology_candidate; BUDGETED, seeded-random default surrogate)',
    params: [
      { name: 'nodes', label: 'Node count', kind: 'int', def: 64, min: 4, help: 'Router count (square k×k required by the generator).' },
      { name: 'iters', label: 'Iterations', kind: 'int', def: 50, min: 1, help: 'Search budget.' },
      { name: 'cluster_size', label: 'Cluster size', kind: 'select', def: 4, options: [4, 8, 16], help: 'Generator dimension.' },
      { name: 'express_length', label: 'Express reach', kind: 'select', def: 1, options: [1, 2, 3], help: 'Generator dimension.' },
      { name: 'radix', label: 'Radix', kind: 'select', def: 4, options: [3, 4, 5], help: 'Generator dimension.' },
      { name: 'intra_weight', label: 'Intra-cluster weight', kind: 'float', def: 1.0, min: 0.5, max: 1.0, help: 'Generator dimension in [0.5, 1.0].' },
      { name: 'inter_weight', label: 'Inter-cluster weight', kind: 'float', def: 0.3, min: 0.1, max: 0.5, help: 'Generator dimension in [0.1, 0.5].' },
      { name: 'seed', label: 'Seed', kind: 'int', def: 7, min: 0, help: 'Deterministic runs require an explicit seed.' },
      { name: 'scorer', label: 'Scorer', kind: 'select', def: 'analytical', options: ['analytical', 'booksim'], help: 'Analytical generator objective or BookSim trace replay.' },
    ],
  },
  {
    id: 'rho',
    label: 'Rolling Horizon (RHO)',
    tagline: 'Local graph mutation with finite-horizon rollout.',
    claim: 'Seed topology, add/remove mutations, connectivity + edge-budget invariants, rolling-horizon evaluation. Best observed among evaluated candidates.',
    completeness: 'UNBOUNDED',
    completenessNote: 'Seed-dependent local search — no claim of global optimality.',
    engine: 'rho_iterative',
    solverStatus: 'FEASIBLE',
    cli: ['veritx', 'synthesize', 'iterative'],
    cliNote: 'CLI verb exists with --method rho.',
    adapter: 'veritx_dse.synthesis.rho_grpo_adapter (run_rho → to_topology_candidate; UNBOUNDED, seeded mutations + horizon rollouts)',
    params: [
      { name: 'nodes', label: 'Node count', kind: 'int', def: 64, min: 4, help: 'Router count.' },
      { name: 'steps', label: 'Steps', kind: 'int', def: 50, min: 1, help: 'Search steps.' },
      { name: 'horizon', label: 'Horizon', kind: 'int', def: 5, min: 1, help: 'Rollout horizon H.' },
      { name: 'branch', label: 'Branch width', kind: 'int', def: 5, min: 1, help: 'Rollout branch width B.' },
      { name: 'max_edges', label: 'Edge budget', kind: 'int', def: 120, min: 1, help: 'Maximum link count invariant.' },
      { name: 'seed', label: 'Seed', kind: 'int', def: 7, min: 0, help: 'Deterministic runs require an explicit seed — bare randomness is refused.' },
    ],
  },
  {
    id: 'grpo',
    label: 'GRPO-style group search',
    tagline: 'Group-relative candidate exploration. Not a trained policy.',
    claim: 'Group evaluation with mean-baseline relative commit. No weights, no gradients — the name records the selection discipline, not a learned model.',
    completeness: 'UNBOUNDED',
    completenessNote: 'Seed-dependent group search — no claim of global optimality.',
    engine: 'grpo_group',
    solverStatus: 'FEASIBLE',
    cli: ['veritx', 'synthesize', 'iterative'],
    cliNote: 'CLI verb exists with --method grpo.',
    adapter: 'veritx_dse.synthesis.rho_grpo_adapter (run_grpo → to_topology_candidate; UNBOUNDED, mean-baseline relative commit — not a trained policy)',
    params: [
      { name: 'nodes', label: 'Node count', kind: 'int', def: 64, min: 4, help: 'Router count.' },
      { name: 'steps', label: 'Steps', kind: 'int', def: 50, min: 1, help: 'Search steps.' },
      { name: 'group', label: 'Group size', kind: 'int', def: 4, min: 2, help: 'Mutants evaluated per step.' },
      { name: 'max_edges', label: 'Edge budget', kind: 'int', def: 120, min: 1, help: 'Maximum link count invariant.' },
      { name: 'seed', label: 'Seed', kind: 'int', def: 7, min: 0, help: 'Deterministic runs require an explicit seed.' },
    ],
  },
];

export function methodById(id: string): SynthesisMethod {
  const found = METHODS.find((m) => m.id === id);
  if (!found) throw new Error(`unknown synthesis method ${id}`);
  return found;
}

export function cliCommand(
  method: SynthesisMethod,
  values: Record<string, string | number>,
  trace: string,
): string[] | null {
  if (method.id === 'bo') {
    const cmd = [
      'veritx', 'synthesize', 'bo',
      '--traffic', trace || '<trace>',
      '--nodes', String(values.nodes ?? 64),
      '--iters', String(values.iters ?? 50),
      '--scorer', String(values.scorer ?? 'analytical'),
    ];
    if (values.seed != null && values.seed !== '') {
      cmd.push('--seed', String(values.seed));
    }
    return cmd;
  }
  if (method.id === 'rho' || method.id === 'grpo') {
    return [
      'veritx', 'synthesize', 'iterative',
      '--trace', trace || '<trace>',
      '--method', method.id,
      '--steps', String(values.steps ?? 50),
      '--max-edges', String(values.max_edges ?? 120),
    ];
  }
  return null;
}
