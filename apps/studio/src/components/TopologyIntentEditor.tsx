import { useRef, useState, type ReactElement } from 'react';
import { api, type FabricPresetCatalogEntry, type TopologyFamilyTruth } from '../api';
import { ErrorBox, Link, useAsync } from '../studio';

const NAMES: Record<string, string> = {
  mesh: 'Mesh', concentrated_mesh: 'Concentrated mesh', torus: 'Torus',
  flatfly: 'FlatFly', flattened_butterfly: 'Flattened butterfly',
  dragonfly: 'Dragonfly', fat_tree: 'Fat tree (structured)', fattree: 'Fat tree',
  qtree: 'QTree', tree4: 'Tree4', explicit: 'Custom graph', srota: 'SROTA',
  gec_mesh: 'GEC mesh', gec_express: 'GEC express',
  gec_multidrop: 'GEC MECS', gec_hybrid: 'GEC hybrid',
};
const LABELS: Record<string, string> = {
  side_length: 'Grid side (routers)', grid_side_length: 'Grid side (routers)',
  concentration: 'Endpoints per router', radix_per_dimension: 'Radix per dimension',
  dimension_count: 'Dimensions', switch_radix: 'Switch radix', level_count: 'Levels',
  express_channel_groups_per_dimension: 'Express groups per dimension',
  destinations_per_express_channel: 'Destinations per express wire',
  mecs_row: 'Row MECS', mecs_col: 'Column MECS', drop_latency: 'Drop latency (cycles)',
  path_shapes: 'Path shapes', vc_policy: 'VC policy', planes: 'Planes',
  island_columns: 'Island columns', tel_period: 'Telemetry period (cycles)',
  tel_latency: 'Telemetry latency (cycles)', sidebuf_enable: 'Side buffer',
  sidebuf_watermark: 'Side-buffer watermark',
};
const ROUTER_CONTROLS = [
  ['input_buffer_depth_flits_per_vc', 'Input buffer (flits per VC)', 1, 64],
  ['credit_return_latency_cycles', 'Credit return (cycles)', 0, 16],
  ['allocator_iterations', 'Allocator iterations', 1, 16],
  ['route_compute_cycles', 'Route compute (cycles)', 1, 16],
  ['vc_alloc_cycles', 'VC allocation (cycles)', 1, 16],
  ['switch_alloc_cycles', 'Switch allocation (cycles)', 1, 16],
  ['switch_traversal_cycles', 'Switch traversal (cycles)', 1, 16],
] as const;

export function topologyFamily(doc: Record<string, unknown>): string {
  const topology = doc.topology as Record<string, unknown> | undefined;
  if (topology?.kind === 'structured') return String(topology.family);
  if (topology?.kind === 'gec') return `gec_${String(topology.mode)}`;
  if (typeof topology?.kind === 'string') return topology.kind;
  const noc = doc.noc_config as Record<string, unknown> | undefined;
  const legacy = String(noc?.topology_family ?? 'mesh');
  return legacy === 'custom' ? 'explicit' : legacy;
}
export const topologyName = (doc: Record<string, unknown>): string => {
  const family = topologyFamily(doc);
  return NAMES[family] ?? family;
};

function JsonField({ value, label, disabled, onChange }: {
  value: unknown; label: string; disabled: boolean; onChange: (value: unknown) => void;
}): ReactElement {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState('');
  return (
    <div className="field">
      <label className="field">
        <span className="field-label">{label}</span>
        <textarea value={text} disabled={disabled} rows={Array.isArray(value) ? 2 : 8}
          onChange={(event) => { setText(event.target.value); setError(''); }} />
      </label>
      {!disabled && <button className="btn btn-small" type="button" onClick={() => {
        try {
          const next: unknown = JSON.parse(text);
          if (Array.isArray(value) ? !Array.isArray(next)
            : !next || typeof next !== 'object' || Array.isArray(next)) {
            throw new Error(Array.isArray(value) ? 'Enter a JSON list.' : 'Enter a JSON object.');
          }
          onChange(next);
          setError('');
        } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
      }}>Apply {label.toLowerCase()}</button>}
      {error && <p className="bad" role="alert">{error}</p>}
    </div>
  );
}

export default function TopologyIntentEditor({ doc, onChange, readOnly, projectId }: {
  doc: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void;
  readOnly: boolean; projectId?: string;
}): ReactElement {
  const caps = useAsync(() => api.loomCapabilities(true), []);
  const presets = useAsync(() => api.fabricPresets(), []);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const latestDoc = useRef(doc);
  latestDoc.current = doc;
  const family = topologyFamily(doc);
  const topology = doc.topology as Record<string, unknown> | undefined;
  const families = caps.result.state === 'ready' && caps.result.data.topology.probed
    ? caps.result.data.topology.families ?? [] : [];
  const catalog = presets.result.state === 'ready' ? presets.result.data.presets : [];
  const truth = families.find((item) => item.family === family);
  const ready = caps.result.state === 'ready' && presets.result.state === 'ready'
    && caps.result.data.topology.probed;
  const disabled = readOnly || pending;
  const controls = (doc.noc_controls ?? {}) as Record<string, unknown>;
  const hasRouterControls = ROUTER_CONTROLS.some(([key]) => controls[key] != null);

  const adopt = async (preset: FabricPresetCatalogEntry): Promise<void> => {
    setError(null);
    if (doc.schema_version === 4) {
      const next: Record<string, unknown> = { ...doc, topology: structuredClone(preset.topology) };
      delete next.synthesis_provenance;
      onChange(next);
      return;
    }
    if (!projectId) return;
    const snapshot = doc;
    setPending(true);
    try {
      const preview = await api.previewTopology(projectId, snapshot, preset.topology);
      if (latestDoc.current !== snapshot) {
        throw new Error('The draft changed while loading the topology. Select it again.');
      }
      onChange(preview.request);
    } catch (err) { setError(err instanceof Error ? err : new Error(String(err))); }
    finally { setPending(false); }
  };
  const write = (key: string, value: unknown, nested = false): void => {
    if (!topology) return;
    const next = nested ? { ...topology, params: {
      ...(topology.params as Record<string, unknown>), [key]: value,
    } } : { ...topology, [key]: value };
    onChange({ ...doc, topology: next });
  };
  const field = (key: string, value: unknown, nested = false): ReactElement => {
    const label = LABELS[key] ?? key.replace(/_/g, ' ').replace(/^./, (s) => s.toUpperCase());
    if (Array.isArray(value) || (value && typeof value === 'object')) {
      return <JsonField key={`${family}-${key}-${JSON.stringify(value)}`} label={label}
        value={value} disabled={disabled} onChange={(next) => write(key, next, nested)} />;
    }
    return <label className="field" key={key}>
      <span className="field-label">{label}</span>
      {typeof value === 'boolean' ? (
        <input type="checkbox" checked={value} disabled={disabled}
          onChange={(event) => write(key, event.target.checked, nested)} />
      ) : (
        <input type={typeof value === 'number' || value == null ? 'number' : 'text'}
          step={1} value={value == null ? '' : String(value)} disabled={disabled}
          onChange={(event) => write(key, typeof value === 'number' || value == null
            ? event.target.value === '' ? null : Number(event.target.value)
            : event.target.value, nested)} />
      )}
    </label>;
  };
  const entries = Object.entries(topology ?? {}).filter(([key]) =>
    !['kind', 'family', 'mode', 'params', 'graph'].includes(key));
  const guided = new Set(['side_length', 'grid_side_length', 'concentration',
    'radix_per_dimension', 'dimension_count', 'switch_radix', 'level_count',
    'express_channel_groups_per_dimension', 'destinations_per_express_channel']);
  const advanced = entries.filter(([key]) => !guided.has(key));
  const torusDeps = catalog.find((preset) => preset.family === 'torus')?.dependencies ?? [];
  const dependencies = (doc.dependencies ?? []) as Record<string, unknown>[];
  const missingDeps = torusDeps.filter((required) => !dependencies.some((dep) =>
    dep.source === required.source && dep.target === required.target && dep.kind === required.kind));
  const capabilityError = caps.result.state === 'error' ? caps.result.error
    : presets.result.state === 'error' ? presets.result.error : null;
  return (
    <section className="topology-intent" aria-label="Topology intent" aria-busy={pending}>
      <label className="field">
        <span className="field-label">Topology</span>
        <select value={family} disabled={disabled || !ready || (!topology && !projectId)}
          onChange={(event) => {
            const preset = catalog.find((item) => item.family === event.target.value);
            if (preset) void adopt(preset);
          }}>
          {!families.some((item) => item.family === family) && (
            <option value={family}>{topologyName(doc)} (current draft)</option>
          )}
          {families.map((item: TopologyFamilyTruth) => (
            <option key={item.family} value={item.family}
              disabled={!catalog.some((preset) => preset.family === item.family)
                || item.status !== 'READY'}>
              {NAMES[item.family] ?? item.family} — {item.status}
            </option>
          ))}
        </select>
      </label>
      {!ready && !capabilityError && <p className="muted" role="status">Checking topology support…</p>}
      {capabilityError && <><ErrorBox error={capabilityError} />
        <button className="btn btn-small" onClick={() => { caps.reload(); presets.reload(); }}>Retry topology catalog</button></>}
      {pending && <p className="muted" role="status">Preparing typed topology…</p>}
      {error && <ErrorBox error={error} />}
      <div className="form-grid">
        {entries.filter(([key]) => guided.has(key)).map(([key, value]) => field(key, value))}
        {Object.entries((topology?.params ?? {}) as Record<string, unknown>)
          .map(([key, value]) => field(key, value, true))}
      </div>
      {family === 'torus' && missingDeps.length > 0 && (
        <div role="note">
          <p className="muted">The qualified torus profile needs an odd grid side and explicit X/Y blocking dependencies.</p>
          {!readOnly && <button className="btn btn-small" disabled={pending} onClick={() =>
            onChange({ ...doc, dependencies: [...dependencies, ...missingDeps] })}>
            Add torus X/Y dependencies
          </button>}
        </div>
      )}
      {family === 'torus' && missingDeps.length === 0 && <p className="muted">Torus profile: odd grid side, two dateline VCs derived from X/Y dependencies.</p>}
      {topology?.kind === 'explicit' && <details className="subtle">
        <summary>Custom graph definition</summary>
        <JsonField key={JSON.stringify(topology.graph)} label="Graph JSON" value={topology.graph}
          disabled={disabled} onChange={(next) => write('graph', next)} />
        {projectId && <Link className="link" to={`/projects/${projectId}/loom/topology`}>Open graph workspace</Link>}
      </details>}
      {advanced.length > 0 && <details className="subtle">
        <summary>Topology options</summary>
        <div className="form-grid">{advanced.map(([key, value]) => field(key, value))}</div>
      </details>}
      {doc.schema_version === 4 && <details className="subtle" open={readOnly && hasRouterControls ? true : undefined}>
        <summary>Router buffers and timing</summary>
        <p className="muted">Leave every field blank to keep the existing backend profile. Setting any field selects the authored IQ-router profile: unset fields use 16 flits per VC, one credit-return cycle, one allocator iteration, and one cycle per pipeline stage. Execution requires iSLIP and one-cycle VC/switch allocation; SROTA requires its side buffer off. Compile checks the exact configuration. These are simulator controls, not hardware signoff.</p>
        <div className="form-grid">
          {ROUTER_CONTROLS.map(([key, label, min, max]) => <label className="field" key={key}>
            <span className="field-label">{label}</span>
            <input type="number" step={1} min={min} max={max}
              value={controls[key] == null ? '' : String(controls[key])} disabled={disabled}
              onChange={(event) => {
                const next = { ...controls };
                if (event.target.value === '') delete next[key];
                else next[key] = Number(event.target.value);
                onChange({ ...doc, noc_controls: next });
              }} />
          </label>)}
        </div>
      </details>}
      <details className="subtle">
        <summary>Presets and capability details</summary>
        <p className="muted">Changing families starts from a shipped preset's topology only. Workload, agents, goals, and dependencies stay unchanged. Save and compile to validate this configuration.</p>
        <label className="field"><span className="field-label">Topology preset</span>
          <select value="" disabled={disabled || !ready} onChange={(event) => {
            const preset = catalog.find((item) => item.preset_id === event.target.value);
            if (preset) void adopt(preset);
          }}>
            <option value="">Start from a preset…</option>
            {catalog.filter((item) => item.family === family).map((item) => (
              <option key={item.preset_id} value={item.preset_id}>{item.description}</option>
            ))}
          </select>
        </label>
        {truth && <><p className="muted">{truth.reason}</p>
          <p className="muted">Qualified profile: <code>{truth.qualification ?? 'Unavailable'}</code></p></>}
      </details>
    </section>
  );
}
