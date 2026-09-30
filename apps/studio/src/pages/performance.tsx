import { useState, type ReactElement } from 'react';
import {
  api,
  type FederatedAnalysisView,
  type NormalizedMetricView,
} from '../api';
import { AsyncView, useAsync } from '../studio';
import { fmtNum } from '../components/badges';
import {
  EpistemicChip,
  ScientificValue,
} from '../components/ScientificValue';

const UNCALIBRATED = 'PREDICTIVE VALIDATION NOT ESTABLISHED';

function isModelAnalysis(a: FederatedAnalysisView): boolean {
  const f = (a.model_fidelity ?? '').toLowerCase();
  if (f.includes('model') || f.includes('analytical') || f.includes('wave')) {
    return true;
  }
  const keys = (a.normalized_metrics ?? []).map((m) =>
    m.key.toLowerCase());
  return keys.some((k) =>
    k.includes('makespan') || k.includes('critical') ||
    k.includes('latency') || k.includes('utiliz') ||
    k.includes('sensitivity'));
}

type MetricGroup =
  | 'makespan' | 'critical' | 'latency' | 'utilization' | 'sensitivity'
  | 'other';

function groupOf(key: string): MetricGroup {
  const k = key.toLowerCase();
  if (k.includes('critical')) return 'critical';
  if (k.includes('makespan')) return 'makespan';
  if (k.includes('sensitivity')) return 'sensitivity';
  if (k.includes('utiliz')) return 'utilization';
  if (k.includes('latency')) return 'latency';
  return 'other';
}

function ModelMetric({ metric }: { metric: NormalizedMetricView }): ReactElement {
  return (
    <div className="kv">
      <span><code>{metric.key}</code></span>
      <span>
        <ScientificValue
          value={metric.value}
          unit={metric.unit}
          epistemic="MODELLED"
          source={metric.source_metric_key ?? 'Wave-E model'}
          fidelity="dependency model"
          qualification={UNCALIBRATED}
        />
      </span>
    </div>
  );
}

function groupTitle(group: MetricGroup): string {
  switch (group) {
    case 'makespan': return 'Makespan';
    case 'critical': return 'Critical path';
    case 'latency': return 'Request latency';
    case 'utilization': return 'Resource utilization';
    case 'sensitivity': return 'Sensitivity';
    case 'other': return 'Other model metrics';
  }
}

function ModelAnalysisCard({ analysis }: {
  analysis: FederatedAnalysisView;
}): ReactElement {
  const metrics = analysis.normalized_metrics ?? [];
  const groups = new Map<MetricGroup, NormalizedMetricView[]>();
  for (const m of metrics) {
    const g = groupOf(m.key);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)?.push(m);
  }
  const order: MetricGroup[] = [
    'makespan', 'critical', 'latency', 'utilization', 'sensitivity',
    'other',
  ];
  return (
    <section className="card">
      <h3>
        {analysis.question} <EpistemicChip value="MODELLED" />
      </h3>
      <p className="muted">
        Model output — {UNCALIBRATED.toLowerCase()}. Native evidence{' '}
        <code>{analysis.native_evidence_id ?? '—'}</code>
        {(analysis.limitations ?? []).length > 0 && (
          <> · limitations: {analysis.limitations?.join('; ')}</>
        )}
      </p>
      {order.filter((g) => (groups.get(g) ?? []).length > 0).map((g) => (
        <div key={g}>
          <h4>{groupTitle(g)}</h4>
          {g === 'critical' && (
            <p className="muted">
              Explicit dependency-chain critical path. Resource
              serialization is not included in this definition — this is
              the longest chain of declared dependencies by scheduled
              duration, not the realized bottleneck.
            </p>
          )}
          {g === 'latency' && (
            <p className="muted">
              Mean / median / p95 / max where actually available from the
              model rows — never zero-filled when a row is absent.
            </p>
          )}
          {g === 'sensitivity' && (
            <p className="muted">
              Sensitivity is shown as the nested model result the backend
              carried — it is not reduced to one scalar.
            </p>
          )}
          {(groups.get(g) ?? []).map((m, i) => (
            <ModelMetric key={`${m.key}-${i}`} metric={m} />
          ))}
        </div>
      ))}
      {metrics.length === 0 && (
        <p className="muted">
          This model analysis carries no normalized scalar metrics —
          inspect native evidence for the full schedule/dependency record.
        </p>
      )}
      {analysis.native_summary != null && (
        <details>
          <summary>Native model summary (backend-carried)</summary>
          <pre className="evidence">
            {JSON.stringify(analysis.native_summary, null, 2)}
          </pre>
        </details>
      )}
    </section>
  );
}

function RunPerformance({ runId }: { runId: string }): ReactElement {
  const run = useAsync(() => api.run(runId), [runId]);
  return (
    <AsyncView result={run.result} reload={run.reload}>
      {(r) => {
        const models = (r.analyses ?? []).filter(isModelAnalysis);
        if (models.length === 0) {
          return (
            <p className="muted">
              Run <code>{runId}</code> carries no Wave-E model analyses.
              Model metrics appear here when an evaluation records them
              under a model/analytical fidelity — they are never
              back-filled from packet simulation.
            </p>
          );
        }
        return (
          <>
            {models.map((a, i) => (
              <ModelAnalysisCard
                key={`${a.question}-${a.backend_id ?? ''}-${i}`}
                analysis={a}
              />
            ))}
          </>
        );
      }}
    </AsyncView>
  );
}

export function Performance({ projectId }: {
  projectId: string;
}): ReactElement {
  const runs = useAsync(() => api.runs({ projectId }), [projectId]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  return (
    <div className="page">
      <h2>Performance</h2>
      <section className="card">
        <h3>Model scope</h3>
        <p className="muted">
          Wave-E dependency-model analysis: schedule, makespan, critical
          path, request latency, resource utilization and sensitivity —
          all <EpistemicChip value="MODELLED" /> · {UNCALIBRATED}.
          Declared compute durations stay visibly declared; nothing here is
          a hardware measurement.
        </p>
      </section>
      <AsyncView result={runs.result} reload={runs.reload}>
        {(data) => data.runs.length === 0 ? (
          <p className="muted">
            No runs for this project yet — evaluate a revision first, then
            model analyses recorded against a run appear here.
          </p>
        ) : (
          <>
            <section className="card">
              <h3>Run</h3>
              <div className="form-row">
                <label>
                  Run
                  <select
                    value={activeRunId ?? data.runs[0]?.run_id ?? ''}
                    onChange={(e) => setActiveRunId(e.target.value)}
                  >
                    {data.runs.map((r) => (
                      <option key={r.run_id} value={r.run_id}>
                        {r.display_name ?? r.run_id} ·{' '}
                        {r.status ?? '—'}
                        {r.completion_cycles != null
                          ? ` · ${fmtNum(r.completion_cycles)} cycles`
                          : ''}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </section>
            <RunPerformance
              runId={activeRunId ?? data.runs[0]?.run_id ?? ''}
            />
          </>
        )}
      </AsyncView>
    </div>
  );
}
