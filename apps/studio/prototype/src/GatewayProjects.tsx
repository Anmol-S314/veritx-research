import { useState } from 'react';
import { desktopGatewayBase } from './desktop';
import { GATEWAY_START, GatewayHttpError, gateway, gatewayReason, type ProjectEntry } from './gateway';
import { useProject } from './project';
import { CreateProject } from './ProjectAdmin';
import { Button, Dialog, Empty, Field, Icon, Notice, Properties, Section } from './ui';


export function GatewayProjects() {
  const { projects, listError, listPhase, project, refreshList, load, clear } = useProject();
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [deleting, setDeleting] = useState<ProjectEntry | null>(null);
  const [confirmId, setConfirmId] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const active = project.phase === 'loaded' ? project.data : null;
  const selectedId = project.phase === 'loaded' ? active!.detail.project.project_id : project.phase === 'error' ? project.projectId : selected;

  const requestDelete = (entry: ProjectEntry) => {
    setDeleting(entry);
    setConfirmId('');
    setDeleteError('');
  };
  const confirmDelete = async () => {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError('');
    try {
      await gateway.deleteProject(deleting.project.project_id);
      if (selectedId === deleting.project.project_id) clear();
      setDeleting(null);
      refreshList();
    } catch (error) {
      // The row can be stale: the project may already have been removed by
      // another client. Treat a 404 as "already gone", not as a failed delete.
      if (error instanceof GatewayHttpError && error.status === 404) {
        if (selectedId === deleting.project.project_id) clear();
        setDeleting(null);
        refreshList();
        return;
      }
      setDeleteError(gatewayReason(error));
    } finally {
      setDeleteBusy(false);
    }
  };

  if (listPhase === 'idle' || listPhase === 'checking') return <Section title="Repository gateway projects"><p>Checking <code>{gateway.base}</code> …</p></Section>;

  if (listPhase === 'offline') return <Section title="Repository gateway projects" actions={<Button onClick={refreshList}>Retry</Button>}>
    <Notice tone="amber"><strong>Gateway not reachable at <code>{gateway.base}</code>.</strong> {listError} {desktopGatewayBase ? 'Restart Srota Studio to restart its managed backend, then retry.' : <>Start it with <code>{GATEWAY_START}</code>.</>}</Notice>
  </Section>;

  const needle = query.trim().toLowerCase();
  const visibleProjects = projects.filter(entry => !needle || `${entry.project.name} ${entry.project.project_id}`.toLowerCase().includes(needle));
  const open = (id: string) => { setSelected(id); load(id); };
  const projectsList = (
    <Section title="Repository gateway projects" actions={<Button onClick={refreshList}>Refresh</Button>}>
      <div className="toolbar project-toolbar">
        <label className="search-field"><Icon name="search" /><input aria-label="Filter projects" placeholder="Filter projects by name or id…" value={query} onChange={event => setQuery(event.target.value)} /></label>
      </div>
      {visibleProjects.length ? <div className="table-scroll"><table><thead><tr><th>Project</th><th>Project id</th><th>Active revision</th><th>Runs</th><th>Updated</th><th>Action</th></tr></thead><tbody>
        {visibleProjects.map(entry => <tr key={entry.project.project_id} className={entry.project.project_id === selectedId ? 'selected' : ''}>
          <th>{entry.project.name}</th>
          <td className="mono">{entry.project.project_id}</td>
          <td className="mono">{entry.active_revision_id ?? <span className="muted">no revision</span>}</td>
          <td className="numeric">{entry.runs?.length ?? 0}</td>
          <td className="mono">{entry.project.updated_at.slice(0, 19).replace('T', ' ')}</td>
          <td><div className="actions"><Button onClick={() => open(entry.project.project_id)}>{entry.project.project_id === selectedId ? 'Reload' : 'Load'}</Button>{entry.project.project_id === selectedId && <Button danger onClick={() => requestDelete(entry)}>Delete…</Button>}</div></td>
        </tr>)}
      </tbody></table></div> : needle ? <Empty icon="search" title="No project matches this filter">Clear the filter to see every project in the gateway store.</Empty> : <Empty icon="folder" title="The store holds no projects">Create one below.</Empty>}
      {project.phase === 'loading' && <p>Loading {project.projectId} …</p>}
      {project.phase === 'error' && <Notice tone="red">Could not load {project.projectId}: {project.reason}</Notice>}
    </Section>
  );

  return <>
    {projectsList}
    <CreateProject onCreated={id => { refreshList(); setTimeout(() => { open(id); window.location.hash = '/workloads/workflow'; }, 600); }} />
    {deleting && <Dialog title="Delete a gateway project?" onClose={() => { if (!deleteBusy) setDeleting(null); }}>
      <Notice tone="red"><strong>This removes the project directory, its revisions and runs.</strong> It cannot be undone from this page.</Notice>
      <Properties rows={[
        ['Project', deleting.project.name],
        ['Project id', <span className="mono">{deleting.project.project_id}</span>],
        ['Active revision', <span className="mono">{deleting.active_revision_id ?? 'none'}</span>],
        ['Runs', String(deleting.runs?.length ?? 0)],
      ]} />
      <Field label={`Type ${deleting.project.project_id} to confirm`}>
        <input aria-label="Delete confirmation" value={confirmId} onChange={e => setConfirmId(e.target.value)} placeholder={deleting.project.project_id} />
      </Field>
      {deleteError && <Notice tone="red">{deleteError}</Notice>}
      <div className="dialog-actions">
        <Button onClick={() => setDeleting(null)} disabled={deleteBusy}>Cancel</Button>
        <Button danger disabled={deleteBusy || confirmId !== deleting.project.project_id} onClick={confirmDelete}>{deleteBusy ? 'Deleting…' : 'Delete permanently'}</Button>
      </div>
    </Dialog>}
  </>;
}
