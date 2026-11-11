import { useEffect, useState, type ReactElement } from 'react';
import { SweepWorkbench } from './SweepWorkbench';
import { parseSweepRows, type SweepEvidence } from './analysisCurves';
import { gateway, gatewayReason } from './gateway';
import { Button } from './ui';
import './analysisCharts.css';

/** Repository-wide fabric evidence: the uniform injection-rate sweep. Reference
 *  experiment, not the selected project's study or run. The measured workload
 *  replay is its own page (Explore → Workload ablations). */
function useSweepEvidence() {
  const [state, setState] = useState<{ data?: SweepEvidence; error?: string; fallback?: string }>({});
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    gateway.topologySweep().then(data => {
      parseSweepRows(data.rows);
      if (live) setState({ data });
    }).catch(async error => {
      const fallback = gatewayReason(error);
      try {
        const response = await fetch('/data/topology_sweep.json', { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const rows: unknown = await response.json();
        const parsed = parseSweepRows(rows);
        if (live) setState({ fallback, data: {
          source_path: 'public/data/topology_sweep.json',
          scope: 'bundled repository snapshot, not selected project or run',
          rows: parsed,
        } });
      } catch (reason) {
        if (live) setState({ error: `Gateway: ${fallback}; bundled snapshot: ${gatewayReason(reason)}` });
      }
    });
    return () => { live = false; };
  }, [version]);
  return { ...state, refresh: () => setVersion(value => value + 1) };
}

export function FabricAblations(): ReactElement {
  const sweep = useSweepEvidence();
  if (sweep.error) return <section className="section"><div className="section-heading"><h2>Repository sweep comparison</h2><div className="actions"><Button onClick={sweep.refresh}>Refresh sweep evidence</Button></div></div>
    <p className="t-bad" role="alert">Sweep evidence unreadable: {sweep.error}</p></section>;
  if (!sweep.data) return <p className="loading-line">Reading sweep evidence…</p>;
  return <SweepWorkbench evidence={sweep.data} onRefresh={sweep.refresh} fallback={sweep.fallback} />;
}
