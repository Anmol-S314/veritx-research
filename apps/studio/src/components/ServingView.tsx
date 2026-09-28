import type { ReactElement } from 'react';
import type {
  CanonicalServingEvidence,
  ServingConfigEntry,
} from '../api';
import { fmtNum } from './badges';
import { EpistemicChip, ScientificValue } from './ScientificValue';

/**
 * Serving view components (§14). All serving numbers are model-internal
 * cycles under the declared service profile — DECLARED/MODELLED, never
 * hardware latency. Summaries over request rows are DERIVED SUMMARY with
 * an explicit sample count. TPOT is never invented.
 */

// ── Service config ────────────────────────────────────────────────────
// What the user pointed the canonical path at: model, trace, instances,
// TP/DP/EP geometry. Batch/token limits live inside the trace and config
// documents the gateway lists — this card names the selected documents
// and the geometry the gateway read from them; it never re-derives them.

export function ServiceConfigCard({ entry }: {
  entry: ServingConfigEntry | null;
}): ReactElement {
  if (!entry) {
    return (
      <section className="card">
        <h3>Service config</h3>
        <p className="muted">
          No cluster config selected — the gateway catalog lists the
          available service-semantics documents.
        </p>
      </section>
    );
  }
  const g = entry.geometry;
  return (
    <section className="card">
      <h3>Service config</h3>
      <div className="kv">
        <span>config</span><span>{entry.display_name}</span>
      </div>
      <div className="kv">
        <span>model</span><span>{g.models.join(', ') || '—'}</span>
      </div>
      <div className="kv">
        <span>hardware</span><span>{g.hardware.join(', ') || '—'}</span>
      </div>
      <div className="kv">
        <span>instances</span>
        <span><ScientificValue value={g.instances} epistemic="DECLARED" source="cluster config" /></span>
      </div>
      <div className="kv">
        <span>TP sizes</span><span>{g.tp_sizes.join(' / ') || '—'}</span>
      </div>
      <div className="kv">
        <span>DP / EP sizes</span>
        <span>
          {(g as { dp_sizes?: number[] }).dp_sizes?.join(' / ') || '—'}
          {' '}· EP {g.ep_sizes.join(' / ') || '—'}
        </span>
      </div>
      <div className="kv">
        <span>nodes</span>
        <span><ScientificValue value={g.num_nodes} epistemic="DECLARED" source="cluster config" /></span>
      </div>
      <p className="muted">
        Batch limits, token limits and the request trace come from the
        selected config and trace documents ({entry.source}) — listed by
        the gateway, validated by the canonical loader, never edited here.
      </p>
    </section>
  );
}

// ── Compute model ─────────────────────────────────────────────────────
// Declared compute assumptions, visibly declared — NOT hardware calibrated.

export function ComputeModelCard({ profileOverrides }: {
  profileOverrides: Record<string, number | string> | null;
}): ReactElement {
  const entries = Object.entries(profileOverrides ?? {});
  return (
    <section className="card">
      <h3>Compute model <EpistemicChip value="DECLARED" /></h3>
      <p className="muted">
        Service durations are declared model inputs under the certified
        linear service profile — exact within the model,{' '}
        <strong>NOT HARDWARE CALIBRATED</strong>. They bind into the run
        identity as declared assumptions.
      </p>
      {entries.length === 0 ? (
        <p className="muted">Certified declared defaults (no overrides).</p>
      ) : (
        <table className="tbl">
          <thead><tr><th>declared input</th><th>value</th></tr></thead>
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k}>
                <td><code>{k}</code></td>
                <td className="num">{String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// ── MOE ───────────────────────────────────────────────────────────────
// Expert routing / dispatch / combine / EP groups as the serving backend
// returned them — serving MoE is its own pathway, never evidence for
// static MoE.

export function MoeCard({ entry, document }: {
  entry: ServingConfigEntry | null;
  document: CanonicalServingEvidence | null;
}): ReactElement {
  const ep = entry?.geometry.ep_sizes ?? [];
  const isMoe = ep.length > 0;
  return (
    <section className="card">
      <h3>MoE</h3>
      {!isMoe ? (
        <p className="muted">
          Dense service path — no expert routing in this config. Serving
          MoE measurements, when present, belong to this serving pathway
          only and are never read as static-MoE evidence.
        </p>
      ) : (
        <>
          <div className="kv">
            <span>EP sizes</span><span>{ep.join(' / ')}</span>
          </div>
          <div className="kv">
            <span>models</span>
            <span>{entry?.geometry.models.join(', ') || '—'}</span>
          </div>
          <p className="muted">
            Expert routing, dispatch and combine execute inside the serving
            scheduler; per-request completion below reflects them as served.
            {document
              ? ` ${document.request_count} request(s) retired over ${document.rounds} round(s).`
              : ''}
          </p>
        </>
      )}
    </section>
  );
}

// ── PIM ───────────────────────────────────────────────────────────────
// Current canonical state: downstream model only, no canonical bridge.

export function PimCard(): ReactElement {
  return (
    <section className="card">
      <h3>PIM</h3>
      <p className="muted">
        <strong>RESEARCH / DOWNSTREAM MODEL</strong> — PIM latency/power
        lives in the downstream serving model with no canonical intent
        bridge. A zero-network marker is not PIM execution. No PIM claims
        are made for serving results on this page.
      </p>
    </section>
  );
}

// ── Results ───────────────────────────────────────────────────────────
// Distributions + per-request table. Summaries are DERIVED SUMMARY over N
// authenticated request rows. No TPOT exists as a proven metric.

function distribution(
  vals: number[],
): { mean: number; median: number; p95: number; max: number } | null {
  const xs = vals.filter((v) => typeof v === 'number' && Number.isFinite(v))
    .sort((a, b) => a - b);
  if (xs.length === 0) return null;
  const q = (p: number): number => {
    const i = Math.min(xs.length - 1, Math.ceil((p / 100) * xs.length) - 1);
    return xs[Math.max(0, i)];
  };
  return {
    mean: xs.reduce((a, b) => a + b, 0) / xs.length,
    median: q(50),
    p95: q(95),
    max: xs[xs.length - 1] ?? NaN,
  };
}

export function ServingResults({ document }: {
  document: CanonicalServingEvidence;
}): ReactElement {
  const rows = document.request_metrics ?? [];
  const ttfts = rows.map((r) => r[1]).filter(
    (v): v is number => typeof v === 'number');
  const comps = rows.map((r) => r[2]).filter(
    (v): v is number => typeof v === 'number');
  const t = distribution(ttfts);
  const c = distribution(comps);
  const n = rows.length;
  const dist = (
    label: string,
    d: { mean: number; median: number; p95: number; max: number } | null,
  ): ReactElement => (
    <div className="kv">
      <span>{label} mean / median / p95 / max</span>
      <span>
        {d == null ? (
          <span className="muted">no authenticated rows</span>
        ) : (
          <ScientificValue
            value={`${fmtNum(d.mean)} / ${fmtNum(d.median)} / ${fmtNum(d.p95)} / ${fmtNum(d.max)}`}
            unit="cycles"
            epistemic="DERIVED"
            source="authenticated request rows"
            fidelity="model-internal serving"
            qualification="absolute latency PARTIAL"
            sampleCount={n}
          />
        )}
      </span>
    </div>
  );
  return (
    <section className="card">
      <h3>Results</h3>
      <p className="muted">
        Model-internal cycles under the declared service profile. Every
        summary below is a DERIVED SUMMARY over {n} authenticated request
        row(s) — never a measured hardware percentile. TPOT is not a
        proven metric and is not shown.
      </p>
      {dist('TTFT', t)}
      {dist('completion', c)}
      <table className="tbl">
        <thead>
          <tr><th>request</th><th>TTFT (cycles)</th><th>completion (cycles)</th></tr>
        </thead>
        <tbody>
          {rows.map(([id, ttft, completion], i) => (
            <tr key={i}>
              <td><code>{id}</code></td>
              <td className="num">{ttft == null ? '—' : fmtNum(ttft)}</td>
              <td className="num">{completion == null ? '—' : fmtNum(completion)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
