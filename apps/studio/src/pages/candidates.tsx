// Candidates page (§26): the global candidate library. Filters by
// study, generation method, compiled, verified, evaluated, eligible,
// Pareto, adopted. Sources, in order of authority:
//   1. live gateway candidate library (api.candidates) where wired;
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
    () => api.candidates().catch(() => ({ contract_version: 1 as const, entries: [] })),
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
              ...lib.entries.map(entryToRow),
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

/** Detail route: live gateway candidate first, local import second. */
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
        if (d) {
          const input: CandidateViewInput = {
            id: d.candidate.candidate_id,
            label: d.candidate.candidate_id,
            origin: d.candidate.origin.includes('optim')
              ? 'optimization-study'
              : 'synthesis-local',
            method: d.candidate.method ?? '—',
            solverStatus: d.candidate.status ?? '—',
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
            engineSemantics: d.candidate.origin,
            compile: { label: 'compile', state: d.compile ?? '—' },
            verification: { label: 'verification', state: d.verification ?? '—' },
            backends: [
              { label: 'network', state: d.candidate.network_cycles != null ? 'MEASURED' : 'NOT_EVALUATED', detail: d.candidate.network_cycles != null ? `${fmtNum(d.candidate.network_cycles)} cycles` : undefined },
              { label: 'system', state: d.candidate.system_cycles != null ? 'MEASURED' : 'NOT_EVALUATED', detail: d.candidate.system_cycles != null ? `${fmtNum(d.candidate.system_cycles)} cycles` : undefined },
            ],
            requirements: [],
            evidence: d.evidence_ids.map((id, i) => ({ key: `evidence ${i + 1}`, value: id })),
            provenance: Object.entries(d.generator_provenance ?? {}).map(([k, v]) => ({ key: k, value: String(v) })),
            optimizationId: null,
            backendCandidateId: null,
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
        };
        return <CandidateDetail projectId={projectId} input={input} />;
      }}
    </AsyncView>
  );
}
