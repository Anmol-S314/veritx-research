import { useEffect, useState } from 'react';
import { gateway, type Topology } from './gateway';
import type { LoadedProject, LoadedRun } from './project';

// Evidence surfaces must use the topology of the revision the run evaluated,
// not whichever revision is active now. When they differ, the historical
// topology is fetched and never silently replaced by the active one.
export function useRunTopology(project: LoadedProject, run: LoadedRun) {
  const [historical, setHistorical] = useState<{ revision: string; topology: Topology } | null>(null);
  useEffect(() => {
    let live = true;
    if (run.detail.revision_id === project.detail.active_revision_id) return;
    setHistorical(null);
    gateway.topology(run.detail.revision_id)
      .then(topology => { if (live) setHistorical({ revision: run.detail.revision_id, topology }); })
      .catch(() => { /* Never substitute the active revision for historical evidence. */ });
    return () => { live = false; };
  }, [run.detail.revision_id, project.detail.active_revision_id]);
  return run.detail.revision_id === project.detail.active_revision_id
    ? project.topology
    : historical?.revision === run.detail.revision_id ? historical.topology : null;
}
