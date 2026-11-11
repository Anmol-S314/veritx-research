/** Deployment builder: model → hardware → serving policy → project draft.
 *
 *  Rationale: docs/design/reviews/deployment-builder.md.
 *
 *  This page is a thin layer over the backend's deployment mapping. It lists
 *  only tracked artifacts (a model config, a hardware fact, a serving trace),
 *  previews the schema-4 intent, and creates a project from it. It never
 *  invents geometry, hardware facts or measured timing: B200 is a declared
 *  datasheet entry and the page says so.
 */
import { useEffect, useMemo, useState, type ReactElement } from 'react';
import {
  api,
  type DeploymentHardwareEntry,
  type DeploymentModelEntry,
  type DeploymentPreviewRequest,
  type DeploymentPreviewView,
  type DeploymentMappingReport,
} from '../api';
import { ErrorBox, useAsync, useStudio } from '../studio';
import { StatusBadge, fmtNum } from '../components/badges';
import { navigate } from '../router';

const PREVIEW_DEBOUNCE_MS = 250;

/** v1 maps one aggregated instance group; PP is fixed and PD is not offered. */
export const DEPLOYMENT_PP_SIZE = 1;

export interface DeploymentBuilderFormState {
  name: string;
  modelName: string;
  hardware: string;
  tpSize: number;
  epSize: number;
  dpInstances: number;
  maxNumSeqs: number;
  maxNumBatchedTokens: number;
  trace: string;
  numReqs: number;
  meshSideLength: number;
  linkWidthBits: number;
  hbmControllersPerRank: number;
}

export const EMPTY_DEPLOYMENT_FORM: DeploymentBuilderFormState = {
  name: '',
  modelName: '',
  hardware: '',
  tpSize: 2,
  epSize: 1,
  dpInstances: 1,
  maxNumSeqs: 32,
  maxNumBatchedTokens: 2048,
  trace: '',
  numReqs: 10,
  meshSideLength: 2,
  linkWidthBits: 128,
  hbmControllersPerRank: 0,
};

/** The exact body `POST /deployment-intent/preview` receives. Pure so the
 *  contract test can pin it without rendering the form. */
/** MoE deployments default EP to TP; dense deployments have no experts. */
export function defaultEpFor(
  modelFamily: string | null | undefined,
  tpSize: number,
): number {
  return modelFamily === 'mixture_of_experts' ? Math.max(1, tpSize) : 1;
}

export function deploymentBody(
  state: DeploymentBuilderFormState,
): DeploymentPreviewRequest {
  return {
    name: state.name.trim(),
    model_name: state.modelName,
    hardware: state.hardware,
    tp_size: state.tpSize,
    pp_size: DEPLOYMENT_PP_SIZE,
    ep_size: state.epSize,
    dp_instances: state.dpInstances,
    max_num_seqs: state.maxNumSeqs,
    max_num_batched_tokens: state.maxNumBatchedTokens,
    trace: state.trace,
    num_reqs: state.numReqs,
    topology: {
      kind: 'mesh',
      side_length: state.meshSideLength,
      concentration: 1,
    },
    link_width_bits: state.linkWidthBits,
    hbm_controllers_per_rank: state.hbmControllersPerRank,
  };
}

type PreviewState =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'error'; error: Error }
  | { state: 'ready'; data: DeploymentPreviewView };

function intValue(raw: string, minimum: number): number {
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? Math.max(minimum, parsed) : minimum;
}

function NumberField({ label, value, min = 0, onChange }: {
  label: string;
  value: number;
  min?: number;
  onChange: (value: number) => void;
}): ReactElement {
  return (
    <label>
      {label}
      <input
        type="number"
        min={min}
        value={value}
        onChange={(event) => onChange(intValue(event.target.value, min))}
      />
    </label>
  );
}

function IssueTable({ report }: { report: DeploymentMappingReport }): ReactElement | null {
  if (report.issues.length === 0) return null;
  return (
    <table className="tbl">
      <thead>
        <tr><th>issue</th><th>message</th><th>path</th></tr>
      </thead>
      <tbody>
        {report.issues.map((issue, index) => (
          <tr key={`${issue.code}-${index}`}>
            <td><code>{issue.code}</code></td>
            <td>{issue.message}</td>
            <td className="muted">{issue.path ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One preview verdict: status, issues, ranks, geometry, derived volumes,
 *  assumptions and the assembled request. */
function DeploymentReport({ preview }: {
  preview: DeploymentPreviewView;
}): ReactElement {
  const { report } = preview;
  const deployment = report.deployment;
  const model = report.model;
  const derived = report.derived;
  if (!deployment && preview.issues.length === 0) {
    return <p className="muted">The preview returned no deployment report.</p>;
  }
  return (
    <>
      <div className="form-row">
        <span>
          <span className="badge-label">intent</span>{' '}
          <StatusBadge status={preview.status} />
        </span>
        {preview.compile && (
          <span>
            <span className="badge-label">compile</span>{' '}
            <StatusBadge status={preview.compile.status} />
          </span>
        )}
        {report.sources.trace.path && (
          <span className="muted">
            trace <code>{report.sources.trace.path}</code>
          </span>
        )}
      </div>
      {preview.compile?.error && <p className="bad">{preview.compile.error}</p>}
      <IssueTable report={report} />
      {deployment && (
        <>
          <h4>Ranks</h4>
          <div className="kv">
            <span>ranks</span>
            <span>{deployment.ranks}</span>
          </div>
          <div className="kv">
            <span>instances</span>
            <span>{deployment.instances}</span>
          </div>
          <div className="kv">
            <span>TP / EP / DP / PP</span>
            <span>
              {deployment.tp} / {deployment.ep} / {deployment.dp} / {deployment.pp}
            </span>
          </div>
        </>
      )}
      {model && (
        <>
          <h4>Model geometry</h4>
          <div className="kv">
            <span>layers · hidden</span>
            <span>{model.layers} · {model.hidden}</span>
          </div>
          <div className="kv">
            <span>heads · KV heads · head dim</span>
            <span>{model.heads} · {model.kv_heads} · {model.head_dim}</span>
          </div>
          <div className="kv">
            <span>experts · top-k</span>
            <span>
              {(model.experts ?? 0) > 0
                ? `${model.experts} · top-${model.top_k ?? 0}`
                : 'dense'}
            </span>
          </div>
          <div className="kv">
            <span>dtype bytes</span>
            <span>{model.dtype_bytes}</span>
          </div>
          {model.weights_bytes != null && (
            <div className="kv">
              <span>weights</span>
              <span>{fmtNum(model.weights_bytes)} B</span>
            </div>
          )}
        </>
      )}
      {derived && (
        <>
          <h4>Derived volumes</h4>
          <div className="kv">
            <span>prefill chunk</span>
            <span>{fmtNum(derived.prefill_chunk_tokens)} tokens</span>
          </div>
          <div className="kv">
            <span>decode batch</span>
            <span>{fmtNum(derived.decode_batch)} requests</span>
          </div>
          <div className="kv">
            <span>TP prefill</span>
            <span>{fmtNum(derived.tp_prefill_bytes)} B</span>
          </div>
          <div className="kv">
            <span>TP decode</span>
            <span>{fmtNum(derived.tp_decode_bytes)} B</span>
          </div>
          <div className="kv">
            <span>EP dispatch</span>
            <span>{fmtNum(derived.ep_dispatch_bytes)} B</span>
          </div>
          <div className="kv">
            <span>EP combine</span>
            <span>{fmtNum(derived.ep_combine_bytes)} B</span>
          </div>
          <div className="kv">
            <span>EP decode dispatch</span>
            <span>{fmtNum(derived.ep_decode_bytes)} B</span>
          </div>
          <div className="kv">
            <span>KV per token</span>
            <span>{fmtNum(derived.kv_bytes_per_token)} B</span>
          </div>
        </>
      )}
      {report.assumptions.length > 0 && (
        <details>
          <summary>Assumptions ({report.assumptions.length})</summary>
          <ul>
            {report.assumptions.map((assumption, index) => (
              <li key={index}>{assumption}</li>
            ))}
          </ul>
        </details>
      )}
      {preview.request && (
        <details>
          <summary>Request JSON</summary>
          <pre className="evidence">
            {JSON.stringify(preview.request, null, 2)}
          </pre>
        </details>
      )}
    </>
  );
}

export function DeploymentBuilder(): ReactElement {
  const { refreshProjects } = useStudio();
  const models = useAsync(api.deploymentModels, []);
  const hardware = useAsync(api.deploymentHardware, []);
  const serving = useAsync(api.servingConfigs, []);
  const [form, setForm] = useState<DeploymentBuilderFormState>(
    EMPTY_DEPLOYMENT_FORM,
  );
  const [preview, setPreview] = useState<PreviewState>({ state: 'idle' });
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const modelEntries: DeploymentModelEntry[] =
    models.result.state === 'ready' ? models.result.data.models : [];
  const hardwareEntries: DeploymentHardwareEntry[] =
    hardware.result.state === 'ready' ? hardware.result.data.hardware : [];
  const traceEntries =
    serving.result.state === 'ready' ? serving.result.data.traces : [];

  // Catalogs choose the first tracked entry; the user can change it after.
  useEffect(() => {
    if (models.result.state !== 'ready') return;
    const entries = models.result.data.models;
    if (entries.length === 0) return;
    setForm((current) => current.modelName
      ? current
      : {
        ...current,
        modelName: entries[0].model_name,
        epSize: defaultEpFor(entries[0].model_family, current.tpSize),
      });
  }, [models.result]);

  useEffect(() => {
    if (hardware.result.state !== 'ready') return;
    const entries = hardware.result.data.hardware;
    if (entries.length === 0) return;
    setForm((current) => current.hardware
      ? current
      : { ...current, hardware: entries[0].hardware_id });
  }, [hardware.result]);

  useEffect(() => {
    if (serving.result.state !== 'ready') return;
    const traces = serving.result.data.traces;
    if (traces.length === 0) return;
    const preferred = serving.result.data.default_trace;
    const initial = traces.some((trace) => trace.source === preferred)
      ? preferred
      : traces[0].source;
    setForm((current) => current.trace
      ? current
      : { ...current, trace: initial });
  }, [serving.result]);

  const selectedModel = modelEntries.find(
    (entry) => entry.model_name === form.modelName,
  ) ?? null;
  const selectedHardware = hardwareEntries.find(
    (entry) => entry.hardware_id === form.hardware,
  ) ?? null;
  const selectedTrace = traceEntries.find(
    (trace) => trace.source === form.trace,
  ) ?? null;
  const measuredServingTiming = selectedHardware != null
    && selectedHardware.timing === 'MEASURED'
    && selectedHardware.serving_profile;

  const body = useMemo(() => deploymentBody(form), [form]);

  // Debounced live preview. A refusal is a regular verdict, not an error.
  useEffect(() => {
    if (!form.modelName || !form.hardware || !form.trace) {
      setPreview({ state: 'idle' });
      return;
    }
    let alive = true;
    const timer = setTimeout(() => {
      setPreview({ state: 'loading' });
      api.previewDeployment(body)
        .then((data) => {
          if (alive) setPreview({ state: 'ready', data });
        })
        .catch((error: unknown) => {
          if (!alive) return;
          setPreview({
            state: 'error',
            error: error instanceof Error ? error : new Error(String(error)),
          });
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [body, form.modelName, form.hardware, form.trace]);

  const previewData = preview.state === 'ready' ? preview.data : null;
  const canCreate = previewData != null
    && previewData.status === 'OK'
    && previewData.compile?.status === 'COMPILED'
    && previewData.request != null
    && !creating;

  const createProject = async (): Promise<void> => {
    if (previewData == null || !canCreate || previewData.request == null) return;
    setCreating(true);
    setCreateError(null);
    try {
      const name = form.name.trim() || 'Deployment intent';
      const project = await api.createProject(name);
      const projectId = project.project.project_id;
      await api.putDraft(projectId, previewData.request);
      refreshProjects();
      navigate(`/projects/${projectId}/workload`);
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  const catalogsLoading = models.result.state === 'loading'
    || hardware.result.state === 'loading'
    || serving.result.state === 'loading';
  const catalogError = models.result.state === 'error'
    ? models.result.error
    : hardware.result.state === 'error'
      ? hardware.result.error
      : serving.result.state === 'error'
        ? serving.result.error
        : null;
  const catalogsEmpty = !catalogsLoading && !catalogError
    && (modelEntries.length === 0 || hardwareEntries.length === 0
      || traceEntries.length === 0);
  const missingCatalogs = [
    modelEntries.length === 0 ? 'tracked model configs' : '',
    hardwareEntries.length === 0 ? 'hardware facts' : '',
    traceEntries.length === 0 ? 'serving traces' : '',
  ].filter(Boolean);

  const update = <K extends keyof DeploymentBuilderFormState>(
    key: K,
    value: DeploymentBuilderFormState[K],
  ): void => {
    setForm((current) => ({ ...current, [key]: value }));
  };
  const chooseModel = (modelName: string): void => {
    const entry = modelEntries.find((item) => item.model_name === modelName);
    setForm((current) => ({
      ...current,
      modelName,
      epSize: defaultEpFor(entry?.model_family, current.tpSize),
    }));
  };
  const chooseTp = (tpSize: number): void => {
    setForm((current) => {
      const entry = modelEntries.find(
        (item) => item.model_name === current.modelName,
      );
      return {
        ...current,
        tpSize,
        epSize: defaultEpFor(entry?.model_family, tpSize),
      };
    });
  };

  return (
    <div className="page">
      <h2>New deployment</h2>
      <p className="muted">
        Compose one aggregated deployment from a tracked model, hardware
        profile and request trace, preview the schema-4 intent, then create a
        project from it. Pipeline parallelism and prefill/decode pools are not
        offered in v1.
      </p>

      {catalogsLoading && (
        <section className="card">
          <p className="muted" role="status" aria-live="polite">
            Loading deployment catalogs…
          </p>
        </section>
      )}

      {catalogError && (
        <section className="card">
          <h3>Catalogs unavailable</h3>
          <ErrorBox
            error={catalogError}
            onRetry={() => {
              models.reload();
              hardware.reload();
              serving.reload();
            }}
          />
        </section>
      )}

      {catalogsEmpty && (
        <section className="card">
          <h3>No deployment inputs</h3>
          <p className="muted">
            The server returned no {missingCatalogs.join(' or ')}, so there is
            nothing to compose. The preview is never built from an invented
            artifact.
          </p>
        </section>
      )}

      {!catalogsLoading && !catalogError && !catalogsEmpty && (
        <>
          <section className="card">
            <h3>Deployment</h3>
            <div className="form-row">
              <label>
                Name
                <input
                  value={form.name}
                  placeholder="Qwen3-30B on B200"
                  onChange={(event) => update('name', event.target.value)}
                />
              </label>
              <label>
                Model
                <select
                  value={form.modelName}
                  onChange={(event) => chooseModel(event.target.value)}
                >
                  {modelEntries.map((entry) => (
                    <option key={entry.model_name} value={entry.model_name}>
                      {entry.model_name} · {entry.model_family}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Hardware
                <select
                  value={form.hardware}
                  onChange={(event) => update('hardware', event.target.value)}
                >
                  {hardwareEntries.map((entry) => (
                    <option key={entry.hardware_id} value={entry.hardware_id}>
                      {entry.display_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {selectedModel && (
              <>
                <div className="kv">
                  <span>model family</span>
                  <span>{selectedModel.model_family}</span>
                </div>
                <div className="kv">
                  <span>geometry</span>
                  <span>
                    {selectedModel.geometry.layers} layers ·{' '}
                    {selectedModel.geometry.hidden} hidden ·{' '}
                    {selectedModel.geometry.heads} heads (
                    {selectedModel.geometry.kv_heads} KV) · head dim{' '}
                    {selectedModel.geometry.head_dim}
                  </span>
                </div>
                <div className="kv">
                  <span>experts · top-k</span>
                  <span>
                    {(selectedModel.geometry.experts ?? 0) > 0
                      ? `${selectedModel.geometry.experts} · top-${selectedModel.geometry.top_k ?? 0}`
                      : 'dense'}
                  </span>
                </div>
                <div className="kv">
                  <span>model source</span>
                  <span><code>{selectedModel.source}</code></span>
                </div>
              </>
            )}

            {selectedHardware && (
              <>
                <div className="kv">
                  <span>hardware</span>
                  <span>{selectedHardware.display_name}</span>
                </div>
                <div className="kv">
                  <span>memory · bandwidth</span>
                  <span>
                    {fmtNum(selectedHardware.memory_bytes)} B ·{' '}
                    {fmtNum(selectedHardware.memory_bandwidth_bytes_per_s)} B/s
                  </span>
                </div>
                <div className="kv">
                  <span>timing</span>
                  <span>
                    {selectedHardware.timing}
                    {!selectedHardware.serving_profile && ' · no serving profile'}
                  </span>
                </div>
                <div className="kv">
                  <span>provenance</span>
                  <span className="muted">
                    {selectedHardware.provenance || '—'}
                  </span>
                </div>
                {measuredServingTiming ? (
                  <p className="muted">
                    Measured serving timing is available for this hardware.
                  </p>
                ) : (
                  <>
                    <p className="muted">
                      Datasheet · serving timing not measured
                    </p>
                    <p className="muted">
                      This hardware has no profiler bundle, so the preview is an
                      intent-only claim: it derives geometry and volumes, not
                      measured serving performance.
                    </p>
                  </>
                )}
              </>
            )}
          </section>

          <section className="card">
            <h3>Serving policy and fabric</h3>
            <div className="form-row">
              <NumberField
                label="TP size"
                min={1}
                value={form.tpSize}
                onChange={chooseTp}
              />
              <NumberField
                label="EP size"
                min={1}
                value={form.epSize}
                onChange={(value) => update('epSize', value)}
              />
              <NumberField
                label="DP instances"
                min={1}
                value={form.dpInstances}
                onChange={(value) => update('dpInstances', value)}
              />
              <label>
                PP size
                <input value={DEPLOYMENT_PP_SIZE} readOnly />
              </label>
              <NumberField
                label="Max sequences"
                min={0}
                value={form.maxNumSeqs}
                onChange={(value) => update('maxNumSeqs', value)}
              />
              <NumberField
                label="Max batched tokens"
                min={0}
                value={form.maxNumBatchedTokens}
                onChange={(value) => update('maxNumBatchedTokens', value)}
              />
            </div>
            <p className="muted">
              PP is fixed at {DEPLOYMENT_PP_SIZE}: v1 maps one aggregated
              instance group, and prefill/decode pools are not offered.
              MoE deployments represent EP as a mode over TP, so v1 accepts EP
              of 1 or the TP size.
            </p>
            <div className="form-row">
              <label>
                Trace
                <select
                  value={form.trace}
                  onChange={(event) => update('trace', event.target.value)}
                >
                  {traceEntries.map((trace) => (
                    <option key={trace.trace_id} value={trace.source}>
                      {trace.display_name} · {trace.requests} requests
                    </option>
                  ))}
                </select>
              </label>
              <NumberField
                label="Requests"
                min={0}
                value={form.numReqs}
                onChange={(value) => update('numReqs', value)}
              />
            </div>
            {selectedTrace && (
              <div className="kv">
                <span>trace source</span>
                <span><code>{selectedTrace.source}</code></span>
              </div>
            )}
            <div className="form-row">
              <NumberField
                label="Mesh side length"
                min={1}
                value={form.meshSideLength}
                onChange={(value) => update('meshSideLength', value)}
              />
              <NumberField
                label="Link width (bits)"
                min={1}
                value={form.linkWidthBits}
                onChange={(value) => update('linkWidthBits', value)}
              />
              <NumberField
                label="HBM controllers per rank"
                min={0}
                value={form.hbmControllersPerRank}
                onChange={(value) => update('hbmControllersPerRank', value)}
              />
            </div>
            <p className="muted">
              The mesh must seat every rank plus any HBM controllers; the
              compiler refuses a topology that cannot.
            </p>
          </section>

          <section className="card">
            <h3>Preview</h3>
            {preview.state === 'idle' && (
              <p className="muted">
                Choose a model, hardware and trace to preview the intent.
              </p>
            )}
            {preview.state === 'loading' && (
              <p className="muted" role="status" aria-live="polite">
                Previewing intent…
              </p>
            )}
            {preview.state === 'error' && <ErrorBox error={preview.error} />}
            {preview.state === 'ready' && (
              <DeploymentReport preview={preview.data} />
            )}
            <div className="form-row">
              <button
                className="btn btn-primary"
                disabled={!canCreate}
                onClick={() => { void createProject(); }}
              >
                {creating ? 'Creating…' : 'Create project'}
              </button>
              <span className="muted">
                {previewData == null
                  ? 'Create is enabled once a preview returns.'
                  : previewData.status !== 'OK'
                    ? 'Create is disabled: the deployment was refused.'
                    : previewData.compile?.status !== 'COMPILED'
                      ? 'Create is disabled: the intent has not compiled.'
                      : 'Creates the project and writes the request as its draft.'}
              </span>
            </div>
            {createError && <p className="bad">{createError}</p>}
          </section>
        </>
      )}
    </div>
  );
}

export default DeploymentBuilder;
