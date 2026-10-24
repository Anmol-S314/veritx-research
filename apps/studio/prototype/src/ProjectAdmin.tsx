import { useEffect, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { Button, Notice } from './ui';

type Preset = { preset_id: string; name?: string; family?: string; generation?: string; description?: string };
type WorkloadEntry = { workload_id: string; display_name?: string; model_family?: string };

export function CreateProject({ onCreated }: { onCreated: (projectId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [mode, setMode] = useState<'preset' | 'blank'>('preset');
  const [presetId, setPresetId] = useState('');
  const [workloadId, setWorkloadId] = useState('');
  const [presets, setPresets] = useState<Preset[]>([]);
  const [workloads, setWorkloads] = useState<WorkloadEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ project_id: string; name: string } | null>(null);

  useEffect(() => {
    if (!open || presets.length) return;
    gateway.presets().then(setPresets).catch(() => setPresets([]));
    gateway.workloads().then(setWorkloads).catch(() => setWorkloads([]));
  }, [open, presets.length]);

  const create = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const detail = mode === 'preset'
        ? await gateway.createProjectFromPreset(presetId, name.trim() || null)
        : await gateway.createProject(name.trim(), workloadId || null);
      const id = detail.project.project_id;
      setResult({ project_id: id, name: detail.project.name });
      setName(''); setPresetId(''); setWorkloadId('');
      onCreated(id);
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(false);
    }
  };

  if (!open) return <div className="toolbar"><Button primary onClick={() => setOpen(true)}>New project</Button></div>;

  return <div className="section">
    <div className="section-heading"><h2>New project</h2><div className="actions"><Button onClick={() => setOpen(false)}>Close</Button></div></div>
    <div className="form-grid">
      <label className="field"><span>Name</span>
        <input value={name} placeholder={mode === 'preset' ? 'Optional; preset name used' : 'Required'} onChange={e => setName(e.target.value)} />
      </label>
      <label className="field"><span>Start from</span>
        <select value={mode} onChange={e => setMode(e.target.value as typeof mode)}>
          <option value="preset">Shipped fabric preset</option>
          <option value="blank">Blank draft</option>
        </select>
      </label>
      {mode === 'preset'
        ? <label className="field"><span>Preset</span>
          <select value={presetId} onChange={e => setPresetId(e.target.value)}>
            <option value="">Select a preset…</option>
            {presets.map(p => <option key={p.preset_id} value={p.preset_id}>{p.preset_id} · {p.family ?? p.generation ?? ''}</option>)}
          </select>
        </label>
        : <label className="field"><span>Workload</span>
          <select value={workloadId} onChange={e => setWorkloadId(e.target.value)}>
            <option value="">None</option>
            {workloads.map(w => <option key={w.workload_id} value={w.workload_id}>{w.display_name ?? w.workload_id}</option>)}
          </select>
        </label>}
    </div>
    <div className="toolbar">
      <Button primary disabled={busy || (mode === 'preset' ? !presetId : !name.trim())} onClick={create}>{busy ? 'Creating…' : 'Create project'}</Button>
      <span className="muted">{mode === 'preset' ? `POST /api/v1/projects/from-preset` : 'POST /api/v1/projects'}</span>
    </div>
    {error && <Notice tone="red">{error}</Notice>}
    {result && <Notice tone="blue">Created {result.name} <span className="mono">({result.project_id})</span>.</Notice>}
  </div>;
}
