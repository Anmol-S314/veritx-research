import { useEffect, useState } from 'react';
import { gateway, gatewayReason, type WorkloadCatalogEntry } from './gateway';
import { Button, Notice } from './ui';

/**
 * Project creation starts from a workload template, matching the guided flow.
 * Fabric-first shipped presets remain an API capability, not a choice in this
 * form: the fabric is selected after the workload demand is declared.
 */
export function CreateProject({ onCreated }: { onCreated: (projectId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [workloadId, setWorkloadId] = useState('');
  const [workloads, setWorkloads] = useState<WorkloadCatalogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ project_id: string; name: string } | null>(null);

  useEffect(() => {
    if (!open || workloads.length) return;
    gateway.workloads().then(setWorkloads).catch(() => setWorkloads([]));
  }, [open, workloads.length]);

  const create = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const detail = await gateway.createProject(name.trim(), workloadId);
      const id = detail.project.project_id;
      setResult({ project_id: id, name: detail.project.name });
      setName(''); setWorkloadId('');
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
        <input value={name} placeholder="Required" onChange={event => setName(event.target.value)} />
      </label>
      <label className="field"><span>Workload template</span>
        <select value={workloadId} onChange={event => setWorkloadId(event.target.value)}>
          <option value="">Select a workload template…</option>
          {workloads.map(workload => <option key={workload.workload_id} value={workload.workload_id}>{workload.display_name ?? workload.workload_id}</option>)}
        </select>
        <small>The project starts from this registry-defined workload. Edit the model identity, parallelism and traffic in the Intent step, then choose a fabric.</small>
      </label>
    </div>
    <div className="toolbar">
      <Button primary disabled={busy || !name.trim() || !workloadId} onClick={create}>{busy ? 'Creating…' : 'Create project'}</Button>
      <span className="muted">The guided flow starts at Flow → Workload.</span>
    </div>
    {error && <Notice tone="red">{error}</Notice>}
    {result && <Notice tone="blue">Created {result.name} <span className="mono">({result.project_id})</span>.</Notice>}
  </div>;
}
