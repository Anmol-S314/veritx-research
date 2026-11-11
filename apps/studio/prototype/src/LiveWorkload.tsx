import { Empty } from './ui';
import { useLoadedProject, type LoadedProject } from './project';

export function WorkloadGate({ children }: { children: (project: LoadedProject) => React.ReactNode }) {
  const project = useLoadedProject();
  if (!project) return <div className="view-main"><Empty title="No project loaded">
    Load a project from <a href="#/shared/projects">Projects &amp; revisions</a> to read its declared workload, traffic, requirements, and compute stages from the gateway.
  </Empty></div>;
  return <>{children(project)}</>;
}
