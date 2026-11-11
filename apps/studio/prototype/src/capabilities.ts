import { useEffect, useState } from 'react';
import { gateway, type LoomTopologyFamily } from './gateway';

// `/loom/capabilities` probes every registered topology family server-side. The probe is
// expensive, so one promise is shared for the page lifetime and uses within the opened tab all
// render the same status table. A probe failure is reported as "unavailable", never as READY.
let cache: Promise<LoomTopologyFamily[]> | null = null;

export function loadTopologyFamilies(): Promise<LoomTopologyFamily[]> {
  if (!cache) cache = gateway.loomCapabilities()
    .then(payload => payload.topology?.families ?? [])
    .catch(() => []);
  return cache;
}

export function useTopologyFamilies(): { phase: 'loading' | 'ready'; families: LoomTopologyFamily[] } {
  const [state, setState] = useState<{ phase: 'loading' | 'ready'; families: LoomTopologyFamily[] }>({ phase: 'loading', families: [] });
  useEffect(() => {
    let live = true;
    loadTopologyFamilies().then(families => { if (live) setState({ phase: 'ready', families }); });
    return () => { live = false; };
  }, []);
  return state;
}

export const familyStatus = (families: LoomTopologyFamily[], family?: string | null) =>
  family ? families.find(row => row.family === family) ?? null : null;

export const statusTone = (status?: string | null) => status === 'READY' ? 'green' as const : status === 'BLOCKED' ? 'red' as const : 'amber' as const;
