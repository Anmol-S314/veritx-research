import { useState } from 'react';
import { GATEWAY_START, gateway } from './gateway';
import { useProject } from './project';
import { CreateProject } from './ProjectAdmin';
import { ProjectFlow } from './ProjectFlow';
import { Badge, Button, Empty, Notice, Properties, Section } from './ui';


export function GatewayProjects() {
  const { health, projects, listError, listPhase, project, refreshList, load, clear } = useProject();
  const [selected, setSelected] = useState<string | null>(null);
  const active = project.phase === 'loaded' ? project.data : null;
  const selectedId = project.phase === 'loaded' ? active!.detail.project.project_id : project.phase === 'error' ? project.projectId : selected;

  if (listPhase === 'idle' || listPhase === 'checking') return <Section title="Repository gateway projects"><p>Checking <code>{gateway.base}</code> …</p></Section>;

  if (listPhase === 'offline') return <Section title="Repository gateway projects" actions={<Button onClick={refreshList}>Retry</Button>}>
    <Notice tone="amber"><strong>Gateway not reachable at <code>{gateway.base}</code>.</strong> {listError} Start it with <code>{GATEWAY_START}</code>.</Notice>
  </Section>;

  const connectedBackends = health ? Object.entries(health.backends).filter(([, v]) => v.binary_present).map(([k]) => k) : [];
  const open = (id: string) => { setSelected(id); load(id); };
  const projectsList = (
    <Section title="Repository gateway projects" actions={<><Badge tone="green">Connected</Badge><Button onClick={refreshList}>Refresh</Button>{active && <Button onClick={() => { clear(); setSelected(null); }}>Return to local draft</Button>}</>}>
      <Properties rows={[[ 'Gateway', `${health?.status ?? 'connected'} · ${gateway.base}` ], ['Backends present', connectedBackends.length ? connectedBackends.join(', ') : 'None' ], ['Projects', String(projects.length) ]]}/>
      {projects.length ? <div className="table-scroll"><table><thead><tr><th>Project</th><th>Project id</th><th>Active revision</th><th>Runs</th><th>Updated</th><th>Action</th></tr></thead><tbody>
        {projects.map(entry => <tr key={entry.project.project_id} className={entry.project.project_id === selectedId ? 'selected' : ''}>
          <th>{entry.project.name}</th>
          <td className="mono">{entry.project.project_id}</td>
          <td className="mono">{entry.active_revision_id ?? <span className="muted">no revision</span>}</td>
          <td className="numeric">{entry.runs?.length ?? 0}</td>
          <td className="mono">{entry.project.updated_at.slice(0, 19).replace('T', ' ')}</td>
          <td><Button onClick={() => open(entry.project.project_id)}>{entry.project.project_id === selectedId ? 'Reload' : 'Load'}</Button></td>
        </tr>)}
      </tbody></table></div> : <Empty title="The store holds no projects">Create one below.</Empty>}
      {project.phase === 'loading' && <p>Loading {project.projectId} …</p>}
      {project.phase === 'error' && <Notice tone="red">Could not load {project.projectId}: {project.reason}</Notice>}
    </Section>
  );

  return <>
    {active && <ProjectFlow active={active} />}
    {projectsList}
    <CreateProject onCreated={id => { refreshList(); setTimeout(() => open(id), 600); }} />
  </>;
}
