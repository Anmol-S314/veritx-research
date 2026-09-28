// Candidates page (§26): the global candidate library. Filters by
// study, generation method, compiled, verified, evaluated, eligible,
// Pareto, adopted. Sources, in order of authority:
//   1. live gateway candidate library (api.candidates) where wired —
//      adopted/status flips read straight from these gateway records;
//   2. optimization-study candidates from the project record;
//   3. local synthesis imports (explicitly local, never backend truth).
// Cards show origin, design delta, network/system/memory results,
// verification and status. Selecting one opens CandidateDetail (§25).
import { useState, type ReactElement } from 'react';
import { AsyncView, Link, useAsync } from '../studio';
import { api, type CandidateLibraryEntry } from '../api';
import { fmtNum, StatusBadge } from '../components/badges';
import { EpistemicChip } from '../components/ScientificValue';
import { ROUTES } from '../components/Synthesis/methods';
import { listCandidates, type LocalCandidate } from '../components/Synthesis/store';
import { CandidateDetail, type CandidateViewInput } from '../components/CandidateDetail';

interface Row {
  key: string;
  label: string;
  origin: string;
  method: string;
  status: string;
  verification: string;
  network: number | null;
  system: number | null;
  memory: number | null;
  pareto: boolean | null;
  adopted: boolean;
  evaluated: boolean;
  eligible: boolean | null;
  entry: CandidateLibraryEntry | null;
  local: LocalCandidate | null;
  optimizationId: string | null;
  backendCandidateId: string | null;
}

function localToRow(c: LocalCandidate): Row {
  return {
    key: `local:${c.id}`,
    label: c.label,
    origin: 'synthesis-local',
    method: c.method,
    status: 'IMPORTED',
    verification: c.verifyState,
    network: null,
    system: null,
    memory: null,
    pareto: null,
    adopted: false,
    evaluated: false,
    eligible: null,
    entry: null,
    local: c,
    optimizationId: null,
    backendCandidateId: null,
  };
}

/** Raw gateway store record (product/vnext list_candidates) — the library
 * route returns store records, not the display entry shape. Normalized
 * here so adopted/status flips come from the record, never local state. */
interface RawLibraryRecord {
  candidate_id: string;
  origin: { kind: string; synthesis_id?: string } | string | null;
  method?: string | null;
  engine?: string | null;
  solver_status?: string | null;
  status?: string | null;
  compiled?: boolean | null;
  verified?: boolean | null;
  evaluated?: boolean | null;
  adopted?: boolean | null;
  pareto_member?: boolean | null;
  network_cycles?: number | null;
  system_cycles?: number | null;
  memory_cycles?: number | null;
  design_delta?: string | null;
  verification?: string | null;
}

function isRawRecord(e: CandidateLibraryEntry | RawLibraryRecord): e is RawLibraryRecord {
  const origin = (e as RawLibraryRecord).origin;
  return typeof origin !== 'string' || 'compiled' in e;
}

function rawToRow(e: RawLibraryRecord): Row {
  const origin = typeof e.origin === 'string'
    ? e.origin
    : (e.origin?.kind ?? 'unknown');
  const evaluated = e.evaluated === true
    || e.network_cycles != null || e.system_cycles != null || e.memory_cycles != null;
  const status = e.adopted === true ? 'ADOPTED'
    : evaluated ? 'EVALUATED'
    : e.verified === true ? 'VERIFIED'
    : e.compiled === true ? 'COMPILED'
    : (e.solver_status ?? e.status ?? '—');
  return {
    key: `lib:${e.candidate_id}`,
    label: e.candidate_id,
    origin,
    method: e.method ?? e.engine ?? '—',
    status,
    verification: e.verified === true ? 'VERIFIED'
      : (e.verification ?? (e.compiled === true ? 'COMPILED_UNVERIFIED' : 'NOT_VERIFIED')),
    network: e.network_cycles ?? null,
    system: e.system_cycles ?? null,
    memory: e.memory_cycles ?? null,
    pareto: e.pareto_member ?? null,
    adopted: e.adopted === true,
    evaluated,
    eligible: null,
    entry: null,
    local: null,
    optimizationId: null,
    backendCandidateId: null,
  };
}

function entryToRow(e: CandidateLibraryEntry): Row {
  const evaluated =
    e.network_cycles != null || e.system_cycles != null || e.memory_cycles != null;
  return {
    key: `lib:${e.candidate_id}`,
    label: e.candidate_id,
    origin: e.origin,
    method: e.method ?? '—',
    status: e.status ?? '—',
    verification: e.verification ?? '—',
    network: e.network_cycles,
    system: e.system_cycles,
    memory: e.memory_cycles,
    pareto: e.pareto_member,
    adopted: e.adopted,
    evaluated,
    eligible: null,
    entry: e,
    local: null,
    optimizationId: null,
    backendCandidateId: null,
  };
}

export function Candidates({
  projectId,
  candidateId,
}: {
  projectId: string;
  candidateId?: string | null;
}): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  const library = useAsync(
    // The gateway library route returns raw store records
    // ({candidates, count}); the typed display shape is normalized below.
    // A refused/unwired route yields an empty library — never a fixture.
    () => api.candidates()
      .then((lib) => {
        const raw = lib as unknown as {
          entries?: (CandidateLibraryEntry | RawLibraryRecord)[];
          candidates?: RawLibraryRecord[];
        };
        const rows = raw.entries ?? raw.candidates ?? [];
        return { entries: rows };
      })
      .catch(() => ({ entries: [] as (CandidateLibraryEntry | RawLibraryRecord)[] })),
    [],
  );

  const [method, setMethod] = useState('');
  const [origin, setOrigin] = useState('');
  const [onlyEvaluated, setOnlyEvaluated] = useState(false);
  const [onlyPareto, setOnlyPareto] = useState(false);
  const [onlyAdopted, setOnlyAdopted] = useState(false);

  if (candidateId) {
    return <CandidateRoute projectId={projectId} candidateId={candidateId} />;
  }

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <AsyncView result={library.result} reload={library.reload}>
          {(lib) => {
            const rows: Row[] = [
              ...lib.entries.map((e) => (isRawRecord(e) ? rawToRow(e) : entryToRow(e))),
              ...listCandidates().map(localToRow),
            ];
            const methods = [...new Set(rows.map((r) => r.method))].sort();
            const origins = [...new Set(rows.map((r) => r.origin))].sort();
            const shown = rows.filter(
              (r) =>
                (!method || r.method === method) &&
                (!origin || r.origin === origin) &&
                (!onlyEvaluated || r.evaluated) &&
                (!onlyPareto || r.pareto === true) &&
                (!onlyAdopted || r.adopted),
            );
            return (
              <div className="page">
                <h2>Candidates</h2>
                <p className="muted">
                  Every parameter-search and topology-synthesis candidate in
                  one library — so candidates stop disappearing inside a
                  single study page. Generator scores are proposals, never
                  measurements.{' '}
                  <Link to={ROUTES.synthesize(projectId)}>Synthesize</Link>
                </p>
                <section className="card">
                  <h3>Filters</h3>
                  <div className="form-row">
                    <label>Study / origin
                      <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
                        <option value="">all origins</option>
                        {origins.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </label>
                    <label>Generation method
                      <select value={method} onChange={(e) => setMethod(e.target.value)}>
                        <option value="">all methods</option>
                        {methods.map((m) => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </label>
                    <label className="check">
                      <input type="checkbox" checked={onlyEvaluated} onChange={(e) => setOnlyEvaluated(e.target.checked)} />
                      evaluated
                    </label>
                    <label className="check">
                      <input type="checkbox" checked={onlyPareto} onChange={(e) => setOnlyPareto(e.target.checked)} />
                      Pareto
                    </label>
                    <label className="check">
                      <input type="checkbox" checked={onlyAdopted} onChange={(e) => setOnlyAdopted(e.target.checked)} />
                      adopted
                    </label>
                  </div>
                  <p className="muted">
                    Compiled / verified / eligible states live on each
                    candidate card below — the gateway library carries
                    verification and status per entry.
                  </p>
                </section>
                {shown.length === 0 ? (
                  <p className="muted">
                    No candidates yet. Run an optimization study, synthesize
                    and import a graph, and they will appear here.
                  </p>
                ) : (
                  <section className="card">
                    <table className="live-table">
                      <thead>
                        <tr>
                          <th>candidate</th><th>origin</th><th>method</th>
                          <th>network</th><th>system</th><th>memory</th>
                          <th>verification</th><th>status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shown.map((r) => (
                          <tr key={r.key}>
                            <td>
                              <Link to={ROUTES.candidateDetail(projectId, r.label)}>{r.label}</Link>
                              {r.pareto === true && <span className="muted"> · Pareto</span>}
                              {r.adopted && <span className="muted"> · adopted</span>}
                            </td>
                            <td className="muted">{r.origin}</td>
                            <td className="muted">{r.method}</td>
                            <td>{r.network != null ? fmtNum(r.network) : <span className="muted">—</span>}</td>
                            <td>{r.system != null ? fmtNum(r.system) : <span className="muted">—</span>}</td>
                            <td>{r.memory != null ? fmtNum(r.memory) : <span className="muted">—</span>}</td>
                            <td><StatusBadge status={r.verification} /></td>
                            <td><StatusBadge status={r.status} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </section>
                )}
              </div>
            );
          }}
        </AsyncView>
      )}
    </AsyncView>
  );
}

/** Raw gateway detail record (product/vnext get_candidate): store fields
 * plus seed diff, definition and topology IR — not the display shape. */
interface RawDetailRecord {
  candidate_id: string;
  origin: { kind: string; synthesis_id?: string } | null;
  method?: string | null;
  engine?: string | null;
  nodes: number;
  links: number[][];
  generator_objective?: { name?: string; value?: number | null } | null;
  solver_status?: string | null;
  compiled?: boolean | null;
  verified?: boolean | null;
  evaluated?: boolean | null;
  adopted?: boolean | null;
  adopted_project_id?: string | null;
  completeness?: { completeness?: string; claim?: string } | null;
  provenance?: Record<string, unknown> | null;
  definition?: { definition_id?: string } | null;
  diff_vs_seed?: { added?: number[][]; removed?: number[][] } | null;
}

/** Normalize a raw gateway record. Adopted/compiled/verified/evaluated
 * flips come from the record; the seed diff rebuilds the base graph so
 * the delta view works without a stored base. */
function rawDetailToInput(r: RawDetailRecord): CandidateViewInput {
  const key = (e: number[]): string => {
    const [a, b] = e;
    return `${Math.min(a, b)}-${Math.max(a, b)}`;
  };
  const links = (r.links ?? []).map((e) => [e[0], e[1]] as [number, number]);
  let baseLinks: [number, number][] | null = null;
  let baseLabel = 'seed graph unknown';
  if (r.diff_vs_seed) {
    const added = new Set((r.diff_vs_seed.added ?? []).map(key));
    const kept = links.filter((e) => !added.has(key(e)));
    baseLinks = [...kept, ...((r.diff_vs_seed.removed ?? []).map((e) => [e[0], e[1]] as [number, number]))];
    baseLabel = 'reconstructed seed graph (links − added + removed)';
  }
  const kind = r.completeness?.completeness;
  const completeness = (kind === 'BUDGETED' || kind === 'EXHAUSTIVE' || kind === 'UNBOUNDED') ? kind : 'UNBOUNDED';
  const adopted = r.adopted === true;
  return {
    id: r.candidate_id,
    label: r.candidate_id,
    origin: 'synthesis-gateway',
    adopted,
    adoptionNote: adopted
      ? `adopted${r.adopted_project_id ? ` in project ${r.adopted_project_id}` : ''} — gateway record`
      : null,
    method: r.method ?? r.engine ?? '—',
    solverStatus: r.solver_status ?? '—',
    completeness,
    completenessNote: typeof r.completeness?.claim === 'string'
      ? r.completeness.claim
      : 'gateway-carried completeness',
    nodes: r.nodes,
    gridK: Math.round(Math.sqrt(r.nodes)) || 1,
    links,
    baseLinks,
    baseLabel,
    generatorObjective: r.generator_objective?.value ?? null,
    generatorNote: 'Analytical generator objective — screening only, never measured performance.',
    seed: typeof r.provenance?.seed === 'number' ? r.provenance.seed : null,
    engineSemantics: r.engine ?? r.method ?? '—',
    compile: { label: 'compile', state: r.compiled === true ? 'COMPILED' : 'NOT_COMPILED' },
    verification: { label: 'verification', state: r.verified === true ? 'VERIFIED' : 'NOT_VERIFIED' },
    backends: [
      { label: 'evaluation', state: r.evaluated === true ? 'EVALUATED' : 'NOT_EVALUATED' },
    ],
    requirements: [],
    evidence: [],
    provenance: [
      ...Object.entries(r.provenance ?? {}).map(([kk, v]) => ({ key: kk, value: String(v) })),
      ...(r.definition?.definition_id ? [{ key: 'definition_id', value: String(r.definition.definition_id) }] : []),
      ...(r.origin?.synthesis_id ? [{ key: 'synthesis_id', value: String(r.origin.synthesis_id) }] : []),
    ],
    optimizationId: null,
    backendCandidateId: null,
    gatewayCandidateId: r.candidate_id,
  };
}

/** Detail route: live gateway candidate first, local import second.
 * The gateway detail route returns the raw store record (adopted,
 * compiled/verified/evaluated flags, generator objective, seed diff);
 * the typed display shape is accepted too. Either way the adopted flip
 * comes from the record. */
function CandidateRoute({
  projectId,
  candidateId,
}: {
  projectId: string;
  candidateId: string;
}): ReactElement {
  const detail = useAsync(
    () => api.candidate(candidateId).catch(() => null),
    [candidateId],
  );
  return (
    <AsyncView result={detail.result} reload={detail.reload}>
      {(d) => {
        const raw = d as unknown as Record<string, unknown> | null;
        if (raw && (raw as { candidate?: unknown }).candidate === undefined
          && typeof (raw as { candidate_id?: unknown }).candidate_id === 'string') {
          return (
            <CandidateDetail
              projectId={projectId}
              input={rawDetailToInput(raw as unknown as RawDetailRecord)}
            />
          );
        }
        if (d && (d as { candidate?: unknown }).candidate !== undefined) {
          const typed = d as unknown as {
            candidate: CandidateLibraryEntry;
            compile: string | null;
            verification: string | null;
            evidence_ids: string[];
            generator_provenance: Record<string, unknown> | null;
            promotion?: { promoted?: boolean; message?: string | null } | null;
          };
          const input: CandidateViewInput = {
            id: typed.candidate.candidate_id,
            label: typed.candidate.candidate_id,
            origin: typed.candidate.origin.includes('optim')
              ? 'optimization-study'
              : 'synthesis-local',
            adopted: typed.candidate.adopted === true,
            adoptionNote: typed.promotion?.message
              ?? (typed.candidate.adopted === true ? 'adopted — gateway record' : null),
            method: typed.candidate.method ?? '—',
            solverStatus: typed.candidate.status ?? '—',
            completeness: 'BUDGETED',
            completenessNote: 'gateway-carried entry — completeness per parent study',
            nodes: 0,
            gridK: 1,
            links: [],
            baseLinks: null,
            baseLabel: 'unknown base',
            generatorObjective: null,
            generatorNote: 'Generator fields ride on the synthesis result view, not the library entry.',
            seed: null,
            engineSemantics: typed.candidate.origin,
            compile: { label: 'compile', state: typed.compile ?? '—' },
            verification: { label: 'verification', state: typed.verification ?? '—' },
            backends: [
              { label: 'network', state: typed.candidate.network_cycles != null ? 'MEASURED' : 'NOT_EVALUATED', detail: typed.candidate.network_cycles != null ? `${fmtNum(typed.candidate.network_cycles)} cycles` : undefined },
              { label: 'system', state: typed.candidate.system_cycles != null ? 'MEASURED' : 'NOT_EVALUATED', detail: typed.candidate.system_cycles != null ? `${fmtNum(typed.candidate.system_cycles)} cycles` : undefined },
            ],
            requirements: [],
            evidence: typed.evidence_ids.map((id, i) => ({ key: `evidence ${i + 1}`, value: id })),
            provenance: Object.entries(typed.generator_provenance ?? {}).map(([k, v]) => ({ key: k, value: String(v) })),
            optimizationId: null,
            backendCandidateId: null,
            gatewayCandidateId: null,
          };
          return <CandidateDetail projectId={projectId} input={input} />;
        }
        const local = listCandidates().find(
          (c) => c.id === candidateId || c.label === candidateId,
        );
        if (!local) {
          return (
            <div className="page">
              <p className="muted">
                No candidate {candidateId} in the gateway library or local
                imports. <EpistemicChip value={null} />
              </p>
              <p className="muted">
                <Link to={ROUTES.candidates(projectId)}>Back to Candidates</Link>
              </p>
            </div>
          );
        }
        const { links } = local;
        const input: CandidateViewInput = {
          id: local.id,
          label: local.label,
          origin: 'synthesis-local',
          adopted: false,
          adoptionNote: null,
          method: local.method,
          solverStatus: 'FEASIBLE',
          completeness: 'UNBOUNDED',
          completenessNote: 'local import — heuristic search, best observed among evaluated candidates',
          nodes: local.nodes,
          gridK: Math.round(Math.sqrt(local.nodes)) || 1,
          links,
          baseLinks: null,
          baseLabel: 'local base unknown',
          generatorObjective: local.generatorObjective,
          generatorNote: local.generatorNote,
          seed: local.seed,
          engineSemantics: local.method,
          compile: { label: 'compile', state: local.compileState },
          verification: { label: 'verification', state: local.verifyState },
          backends: [],
          requirements: [],
          evidence: [],
          provenance: [
            { key: 'study', value: local.studyId },
            { key: 'imported', value: local.importedAt },
          ],
          optimizationId: local.backendOptimizationId,
          backendCandidateId: local.backendCandidateId,
          gatewayCandidateId: null,
        };
        return <CandidateDetail projectId={projectId} input={input} />;
      }}
    </AsyncView>
  );
}
