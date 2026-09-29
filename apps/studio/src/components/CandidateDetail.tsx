// Candidate detail page (§25). One page per parameter-search or
// Rationale: docs/decisions/studio.md
import { useState, type ReactElement } from 'react';
import { api } from '../api';
import { post } from '../api/client';
import { ErrorBox, Link } from '../studio';
import { navigate } from '../router';
import { fmtNum, Hash, StatusBadge } from './badges';
import { EpistemicChip, ScientificValue } from './ScientificValue';
import type { CompletenessKind } from './Synthesis/methods';
import { ROUTES } from './Synthesis/methods';
import { degreeOf, diffGraphs, isConnected, maxNode, type Edge } from './Synthesis/graph';
import { TopologyGraph } from './Synthesis/TopologyGraph';

export interface CandidateProvenance {
  key: string;
  value: string;
}

export interface CandidateStateRow {
  label: string;
  state: string;
  detail?: string;
}

export interface CandidateViewInput {
  id: string;
  label: string;
  origin: 'synthesis-local' | 'synthesis-gateway' | 'optimization-study';
  /** Gateway-recorded adoption — flips from the candidate record, never
   *  from local state. */
  adopted: boolean;
  adoptionNote: string | null;
  method: string;
  solverStatus: string;
  completeness: CompletenessKind;
  completenessNote: string;
  nodes: number;
  gridK: number;
  links: Edge[];
  baseLinks: Edge[] | null;
  baseLabel: string;
  generatorObjective: number | null;
  generatorNote: string;
  seed: number | null;
  engineSemantics: string;
  compile: CandidateStateRow;
  verification: CandidateStateRow;
  backends: CandidateStateRow[];
  requirements: CandidateStateRow[];
  evidence: CandidateProvenance[];
  provenance: CandidateProvenance[];
  optimizationId: string | null;
  backendCandidateId: string | null;
  /** Gateway synthesis candidate id — promotes through the canonical
   *  POST /candidates/{id}/promote route (draft only, Compile creates
   *  the revision). Null for local imports (no gateway record yet). */
  gatewayCandidateId: string | null;
}

function StateRow({ row }: { row: CandidateStateRow }): ReactElement {
  return (
    <div className="kv">
      <span>{row.label}</span>
      <span>
        <StatusBadge status={row.state} />
        {row.detail && <div className="muted">{row.detail}</div>}
      </span>
    </div>
  );
}

export function CandidateDetail({
  projectId,
  input,
}: {
  projectId: string;
  input: CandidateViewInput;
}): ReactElement {
  const [promoting, setPromoting] = useState(false);
  const [promoted, setPromoted] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const diff = input.baseLinks ? diffGraphs(input.baseLinks, input.links) : null;
  const deg = degreeOf(input.nodes, input.links);
  const maxDeg = Math.max(0, ...deg);
  const connected = isConnected(input.nodes, input.links);
  const topNode = maxNode(input.links);
  const canPromoteOpt = input.origin === 'optimization-study' &&
    input.optimizationId &&
    input.backendCandidateId;
  const canPromoteSynthesis = input.origin === 'synthesis-gateway' &&
    input.gatewayCandidateId;
  const canPromote = canPromoteOpt || canPromoteSynthesis;

  const promote = async (): Promise<void> => {
    if (!canPromote) return;
    setPromoting(true);
    setError(null);
    try {
      if (canPromoteSynthesis && input.gatewayCandidateId) {
        await post<{ contract_version: number } | Record<string, unknown>>(
          `/candidates/${encodeURIComponent(input.gatewayCandidateId)}/promote`,
          { project_id: projectId },
        );
        setPromoted(
          `Draft updated from synthesis candidate ${input.gatewayCandidateId} ` +
          'through the canonical promotion primitive. ' +
          'Compile to create an immutable revision. ' +
          'Adoption flips on the gateway record — reload to confirm.',
        );
      } else if (input.optimizationId && input.backendCandidateId) {
        const draft = await api.useCandidate(
          input.optimizationId,
          input.backendCandidateId,
        );
        setPromoted(
          `Draft updated from candidate ${input.backendCandidateId} `
          + `(dirty: ${String((draft as { dirty?: boolean }).dirty)}). `
          + 'Compile to create an immutable revision.',
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setPromoting(false);
    }
  };

  return (
    <div className="page">
      <p className="muted">
        <Link to={ROUTES.candidates(projectId)}>Candidates</Link>
        {' / '}{input.label}
      </p>
      <h2>
        {input.label}{' '}
        <span className="muted">
          {input.method} · {input.solverStatus}
        </span>
      </h2>
      <p className="muted">
        Origin: {input.origin === 'optimization-study' ? 'optimization study' : input.origin === 'synthesis-gateway' ? 'gateway synthesis record' : 'local synthesis study'}
        {' · '}completeness: <b>{input.completeness}</b> — {input.completenessNote}
        {' · '}adopted: <b>{input.adopted ? 'yes (gateway record)' : 'no'}</b>
        {input.adoptionNote ? ` — ${input.adoptionNote}` : ''}
      </p>

      <section className="card">
        <h3>Design delta</h3>
        {diff ? (
          <div className="kv-grid">
            <div className="kv"><span>base graph</span><span>{input.baseLabel} · {input.baseLinks?.length ?? 0} links</span></div>
            <div className="kv"><span>candidate graph</span><span>{input.links.length} links</span></div>
            <div className="kv"><span>added links</span><span className="good">+{diff.added.length}</span></div>
            <div className="kv"><span>removed links</span><span className="bad">−{diff.removed.length}</span></div>
            <div className="kv"><span>max degree / radix</span><span>{maxDeg}</span></div>
            <div className="kv"><span>connectivity</span><span>{connected ? <StatusBadge status="CONNECTED" /> : <StatusBadge status="DISCONNECTED" />}</span></div>
            {!connected && (
              <p className="warn">Disconnected graphs can never be promoted — connectivity is a typed refusal, not a penalty.</p>
            )}
          </div>
        ) : (
          <p className="muted">No base graph recorded for this candidate — delta unavailable, graph below is the candidate alone.</p>
        )}
      </section>

      <section className="card">
        <h3>Topology graph</h3>
        <TopologyGraph
          base={input.baseLinks ?? input.links}
          candidate={input.baseLinks ? input.links : null}
          nodes={input.nodes}
          k={input.gridK}
          title={input.baseLinks ? 'base vs candidate (added / removed / kept)' : 'candidate graph'}
        />
      </section>

      <section className="card">
        <h3>Generator provenance (proposal, not measurement)</h3>
        <div className="kv"><span>engine semantics</span><span>{input.engineSemantics}</span></div>
        {input.seed != null && <div className="kv"><span>seed</span><span>{input.seed}</span></div>}
        {input.generatorObjective != null ? (
          <ScientificValue
            value={input.generatorObjective}
            unit="weighted hops"
            epistemic="MODELLED"
            source="synthesis generator objective"
            qualification="NOT QUALIFIED — screening only"
          />
        ) : (
          <p className="muted">No generator score recorded.</p>
        )}
        <p className="muted">{input.generatorNote}</p>
        <div className="kv"><span>highest node id</span><span>{topNode >= 0 ? fmtNum(topNode) : '—'} (nodes address 0…{input.nodes - 1})</span></div>
      </section>

      <section className="card">
        <h3>Compile &amp; verification</h3>
        <StateRow row={input.compile} />
        <StateRow row={input.verification} />
        <p className="muted">
          A candidate is never called verified because a generator likes it —
          verification belongs to the compiled revision, not the proposal.
        </p>
      </section>

      <section className="card">
        <h3>Backend analyses</h3>
        {input.backends.length === 0 ? (
          <p className="muted">No backend analyses recorded for this candidate yet.</p>
        ) : (
          input.backends.map((b) => <StateRow key={b.label} row={b} />)
        )}
      </section>

      <section className="card">
        <h3>Requirements &amp; evidence</h3>
        {input.requirements.length === 0 ? (
          <p className="muted">No requirement verdicts recorded.</p>
        ) : (
          input.requirements.map((r) => <StateRow key={r.label} row={r} />)
        )}
        {input.evidence.map((e) => (
          <div className="kv" key={e.key}>
            <span>{e.key}</span>
            <span><Hash value={e.value} /></span>
          </div>
        ))}
        {input.provenance.map((e) => (
          <div className="kv" key={e.key}>
            <span>{e.key}</span>
            <span className="muted">{e.value}</span>
          </div>
        ))}
      </section>

      <section className="card">
        <h3>Actions</h3>
        <div className="form-row">
          <button
            className="btn"
            onClick={() => navigate(`/projects/${projectId}/simulate`)}
          >
            Evaluate candidate
          </button>
          <button
            className="btn"
            onClick={() => navigate(`/projects/${projectId}/decide`)}
          >
            Compare to base
          </button>
          {canPromote ? (
            <button className="btn btn-primary" disabled={promoting} onClick={promote}>
              {promoting ? 'Promoting…' : 'Promote to draft'}
            </button>
          ) : (
            <span className="muted" title="Local imports carry no gateway record">
              Promotion pending: this local import has no gateway candidate record — submit
              through Synthesize (or import via the canonical
              promote_to_explicit_topology path), then Compile.
            </span>
          )}
        </div>
        <p className="muted">
          <EpistemicChip value="DERIVED" /> Promotion writes an ordinary explicit-topology draft.
          After promotion: <b>Draft updated. Compile to create an immutable revision.</b>
        </p>
        {promoted && <p className="good">{promoted}</p>}
        {error && <ErrorBox error={error} />}
      </section>
    </div>
  );
}
