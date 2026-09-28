import type { ReactElement } from 'react';
import type { RunView } from '../api/types';
import { Link } from '../studio';
import { Hash, StatusBadge } from './badges';
import { EpistemicChip } from './ScientificValue';

// ── Evidence graph (§30) + reuse display (§41) + completeness (§42) ──
// The graph is the record, not an inference: every node renders a carried
// identity; a node the backend did not supply renders as NOT CARRIED,
// never invented. Edges state the anti-transplant relation the backend
// enforces (digest binding, re-hash, conservation), so transplant
// attempts are visibly meaningless rather than silently possible.

type Loose = Record<string, unknown>;

function asLoose(run: RunView): Loose {
  return run as unknown as Loose;
}

export interface GraphNode {
  key: string;
  stage: string;
  label: string;
  hash: string | null | undefined;
  epistemic: string | null;
  detail: string | null;
  to: string | null;
}

export function graphNodes(run: RunView): GraphNode[] {
  const loose = asLoose(run);
  const evaluation = (run.evaluation ?? {}) as Loose;
  const evidenceDoc = (loose.evidence_document ?? {}) as Loose;
  return [
    {
      key: 'design',
      stage: 'authored intent',
      label: 'Design',
      hash: run.design_hash,
      epistemic: 'DECLARED',
      detail: run.workload_id ? `workload ${run.workload_id}` : null,
      to: null,
    },
    {
      key: 'compilation',
      stage: 'compiled revision',
      label: 'Compilation',
      hash: run.revision_id,
      epistemic: 'DERIVED',
      detail: run.qualification_basis
        ? `qualification basis ${run.qualification_basis}` : null,
      to: `/revisions/${run.revision_id}`,
    },
    {
      key: 'fabric',
      stage: 'resolved fabric',
      label: 'Resolved fabric',
      hash: run.bundle_id,
      epistemic: 'DERIVED',
      detail: 'fabric+attachment+mapping bound by hash',
      to: null,
    },
    {
      key: 'prepared',
      stage: 'prepared execution',
      label: 'Prepared execution',
      hash: (run.producer?.input_hash ?? null) as string | null,
      epistemic: 'DERIVED',
      detail: run.producer
        ? `input ${short(run.producer.input_hash)} · config ${short(run.producer.config_hash)}`
        : null,
      to: null,
    },
    {
      key: 'producer',
      stage: 'executing producer',
      label: run.producer ? `Producer · ${run.producer.backend}` : 'Producer',
      hash: (run.producer?.producer_identity ?? null) as string | null,
      epistemic: 'VERIFIED',
      detail: run.producer ? `backend ${run.producer.backend}` : null,
      to: null,
    },
    {
      key: 'native',
      stage: 'native evidence',
      label: 'Native evidence',
      hash: run.evidence?.raw_evidence_digest ?? null,
      epistemic: 'SIMULATED',
      detail: run.evidence ? `evidence ${short(run.evidence.evidence_id)}` : null,
      to: null,
    },
    {
      key: 'normalized',
      stage: 'normalized evidence',
      label: 'Normalized evidence',
      hash: (run.evidence?.stats_digest ?? null) as string | null,
      epistemic: 'DERIVED',
      detail: typeof evaluation.performance_result_id === 'string'
        ? `performance ${short(evaluation.performance_result_id as string)}`
        : 'typed view over native evidence',
      to: null,
    },
    {
      key: 'requirements',
      stage: 'requirement report',
      label: 'Requirement report',
      hash: typeof evidenceDoc.requirement_report_id === 'string'
        ? (evidenceDoc.requirement_report_id as string) : null,
      epistemic: run.requirements ? 'VERIFIED' : null,
      detail: run.requirements_pass == null
        ? null : (run.requirements_pass ? 'requirements pass' : 'requirements not all passing'),
      to: null,
    },
    {
      key: 'candidate',
      stage: 'study membership',
      label: 'Candidate / comparison',
      hash: typeof loose.performance_result_id === 'string'
        ? (loose.performance_result_id as string)
        : (typeof evaluation.performance_result_id === 'string'
          ? (evaluation.performance_result_id as string) : null),
      epistemic: null,
      detail: 'present only when this run belongs to a study or comparison',
      to: null,
    },
  ];
}

const EDGE_LABELS: Record<string, string> = {
  design: 'compiler binds design hash — transplanted inputs refuse',
  compilation: 'certificate binds revision — no result without PASS',
  fabric: 'resolved hashes bind fabric/attachment/mapping',
  prepared: 'bytes re-hashed pre-spawn — post-verify mutation refuses',
  producer: 'binary SHA + manifest pinned — producer swap refuses',
  native: 'digest-verified read — copied bytes refuse',
  normalized: 'typed projection — per-metric source equality checked',
  requirements: 'report identity re-derived — design + evidence bound',
  candidate: 'study rows bind performance_result_id per entry',
};

function short(hash: string | null | undefined): string {
  if (!hash) return '—';
  return hash.length > 18 ? `${hash.slice(0, 12)}…` : hash;
}

function GraphNodeCard({ node }: { node: GraphNode }): ReactElement {
  const body = (
    <>
      <span className="type">{node.stage}</span>
      <strong>{node.label}</strong>{' '}
      <EpistemicChip value={node.epistemic} />
      <div>
        {node.hash
          ? <Hash value={node.hash} />
          : <span className="muted">NOT CARRIED by this run's record</span>}
      </div>
      {node.detail && <div className="muted">{node.detail}</div>}
    </>
  );
  return (
    <div className="artifact">
      {node.to && node.hash ? (
        <Link className="link" to={node.to}>{body}</Link>
      ) : body}
    </div>
  );
}

/** Click-to-inspect evidence graph for one run. */
export function EvidenceGraph({ run }: { run: RunView }): ReactElement {
  const nodes = graphNodes(run);
  return (
    <div className="artifact-chain-wrap">
      <div className="artifact-chain evidence-graph">
        {nodes.map((n) => (
          <details key={n.key} className="evidence-node">
            <summary>
              <GraphNodeCard node={n} />
            </summary>
            <p className="muted">
              anti-transplant: {EDGE_LABELS[n.key] ?? 'digest-bound'}
            </p>
          </details>
        ))}
      </div>
    </div>
  );
}

// ── Reuse display (§41) ───────────────────────────────────────────────
// A reused run names the existing evidence id plus every matched parent.
// The backend decides reuse; Studio renders the decision verbatim. When
// the run carries no reuse record, nothing renders — reuse is never
// implied from a bare evidence id.

export interface ReuseRecord {
  reused_evidence_id: string;
  matched: { parent: string; value: string }[];
}

export function reuseRecord(run: RunView): ReuseRecord | null {
  const loose = asLoose(run);
  const raw = loose.reused_evidence ?? loose.reuse;
  if (!raw || typeof raw !== 'object') return null;
  const rec = raw as Loose;
  const id = rec.reused_evidence_id ?? rec.evidence_id;
  if (typeof id !== 'string' || id.length === 0) return null;
  const matchedRaw = rec.matched_parents ?? rec.matching_parents;
  const matched: { parent: string; value: string }[] = Array.isArray(matchedRaw)
    ? (matchedRaw as Loose[]).map((m) => ({
      parent: String((m as Loose).parent ?? (m as Loose).field ?? '?'),
      value: String((m as Loose).value ?? (m as Loose).digest ?? '?'),
    }))
    : [];
  return { reused_evidence_id: id, matched };
}

export function ReuseBanner({ run }: { run: RunView }): ReactElement | null {
  const rec = reuseRecord(run);
  if (!rec) return null;
  return (
    <div className="card reuse-banner">
      <h4>
        REUSED AUTHENTICATED EVIDENCE{' '}
        <StatusBadge status="REUSED" />
      </h4>
      <div className="kv">
        <span>existing evidence id</span>
        <Hash value={rec.reused_evidence_id} />
      </div>
      <p className="muted">
        No new measurement was created. Reuse was legal because every
        scientific parent below matched — design, workload, backend
        config, producer and semantics versions.
      </p>
      {rec.matched.length > 0 && (
        <table className="tbl">
          <thead><tr><th>matching parent</th><th>value</th></tr></thead>
          <tbody>
            {rec.matched.map((m, i) => (
              <tr key={i}>
                <td>{m.parent}</td>
                <td><Hash value={m.value} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Search completeness panel (§42) ───────────────────────────────────
// One vocabulary for Optimize and Synthesize results. The backend owns
// the counts; Studio renders the claim wording verbatim and never
// upgrades BUDGETED/UNBOUNDED to optimal.

export interface CompletenessFacts {
  completeness: string | null | undefined;
  evaluated_count?: number | null;
  universe_size?: number | null;
  budget?: number | null;
  generated_count?: number | null;
  may_claim_optimality?: boolean | null;
}

export function completenessFacts(study: unknown): CompletenessFacts | null {
  if (!study || typeof study !== 'object') return null;
  const s = study as Loose;
  const raw = (s.completeness ?? s.search_completeness) as Loose | string | null | undefined;
  if (raw == null) return null;
  if (typeof raw === 'string') return { completeness: raw };
  const completeness = raw.completeness;
  if (typeof completeness !== 'string') return null;
  const num = (v: unknown): number | null =>
    (typeof v === 'number' && Number.isFinite(v) ? v : null);
  return {
    completeness,
    evaluated_count: num(raw.evaluated_count ?? s.evaluated_count),
    universe_size: num(raw.universe_size ?? s.universe_size),
    budget: num(raw.budget ?? s.budget),
    generated_count: num(raw.generated_count ?? s.generated_count),
    may_claim_optimality: typeof raw.may_claim_optimality === 'boolean'
      ? raw.may_claim_optimality : null,
  };
}

export function completenessWording(f: CompletenessFacts): string {
  const c = (f.completeness ?? '').toUpperCase();
  if (c === 'EXHAUSTIVE' && f.evaluated_count != null) {
    return `EXHAUSTIVE — evaluated all ${f.evaluated_count} declared candidates.`;
  }
  if (c === 'BUDGETED') {
    const uni = f.universe_size != null ? ` of ${f.universe_size} declared` : '';
    const n = f.evaluated_count ?? f.budget;
    return `BUDGETED — ${n ?? '?'}${uni} candidates evaluated. Best observed among evaluated candidates; no global optimality claim.`;
  }
  const n = f.generated_count ?? f.evaluated_count;
  return `HEURISTIC / UNBOUNDED — ${n ?? '?'} generated graphs explored. No claim of global optimality.`;
}

export function SearchCompletenessPanel({ study }: { study: unknown }): ReactElement | null {
  const facts = completenessFacts(study);
  if (!facts) return null;
  const optimal = facts.may_claim_optimality === true
    && (facts.completeness ?? '').toUpperCase() === 'EXHAUSTIVE';
  return (
    <div className="card completeness-panel">
      <h4>Search completeness</h4>
      <p>
        <StatusBadge status={facts.completeness ?? 'UNKNOWN'} />{' '}
        {completenessWording(facts)}
      </p>
      {!optimal && (
        <p className="muted">
          Only an EXHAUSTIVE study may claim optimality — and only over
          its declared finite design space.
        </p>
      )}
    </div>
  );
}
