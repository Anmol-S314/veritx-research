import type { ReactElement, ReactNode } from 'react';
import { Link } from '../../studio';
import { Hash } from '../../components/badges';
import {
  agentRows, domainsOf, isLoomView, LOOM_VIEWS, parallelismOf, useLoom,
  type LoomData, type LoomViewId,
} from './data';
import TopologyLoom from './TopologyLoom';
import AgentsLoom from './AgentsLoom';
import CatalogLoom from './CatalogLoom';
import DomainsLoom from './DomainsLoom';
import ProblemsPanel from './ProblemsPanel';
import AccessLoom from './AccessLoom';
import FloorplanLoom from './FloorplanLoom';
import WorkloadLoom from './WorkloadLoom';
import SimulationLoom from './SimulationLoom';
import './loom.css';

interface StatusLine {
  left: ReactNode[];
  right: ReactNode;
}

/** The bottom engineering line: one line of fact per view, plus the verdict
 *  that the view's data source is sound (or which artifact is missing). */
function statusFor(view: LoomViewId, data: LoomData): StatusLine {
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;
  const traffic = data.traffic.result.state === 'ready'
    ? data.traffic.result.data : null;
  const lowering = data.lowering.result.state === 'ready'
    ? data.lowering.result.data : null;

  switch (view) {
    case 'topology':
      return {
        left: [
          topology ? `${topology.family} · ${topology.counts.routers} routers` : 'no materialized topology',
          topology ? `${topology.counts.channels} directed channels` : 'compile to materialize',
          `${data.agents.reduce((n, a) => n + a.count, 0)} agents`,
        ],
        right: topology
          ? <span className="t-ok">✓ certified TopologyView bound to {data.revisionId?.slice(0, 12) ?? '—'}</span>
          : <span className="t-warn">● intent only — nothing drawn beyond declared counts</span>,
      };
    case 'agents':
      return {
        left: [
          `${data.agents.length} authored groups`,
          `${data.agents.reduce((n, a) => n + a.count, 0)} instances`,
          '7 authored fields per group',
        ],
        right: <span className="t-ok">✓ agent records read verbatim from the draft</span>,
      };
    case 'catalog': {
      const rows = agentRows(data);
      const kinds = new Set(rows.map((r) => r.kind));
      const seated = rows.filter((r) => r.attached).length;
      return {
        left: [
          `${kinds.size} kinds in use`,
          `${rows.length} declared agents`,
          `${seated} seated`,
        ],
        right: rows.length > 0
          ? <span className={rows.length === seated ? 't-ok' : 't-warn'}>
              {rows.length === seated
                ? '✓ every declared agent has a certified seat'
                : `● ${rows.length - seated} declared agent(s) have no certified seat`}
            </span>
          : <span className="t-warn">● no agents on the draft — nothing to catalog</span>,
      };
    }
    case 'domains': {
      const { rows, crossings } = domainsOf(data);
      const declared = rows.filter((r) => r.id !== 'undeclared').length;
      // Count agents, not rows: clock and power are two tallies over the same
      // agent set, so summing both would double every unassigned agent.
      const undeclared = rows
        .filter((r) => r.kind === 'clock' && r.id === 'undeclared')
        .reduce((n, r) => n + r.agentCount, 0);
      return {
        left: [
          `${declared} declared domains`,
          undeclared > 0 ? `${undeclared} agents unassigned` : 'all agents assigned',
          `${crossings.length} derived crossings`,
        ],
        right: crossings.length > 0
          ? <span className="t-warn">● {crossings.length} channel(s) cross a clock-domain boundary; no synchronizer artifact exists</span>
          : undeclared > 0
            ? <span className="t-warn">● no agent declares a clock domain — crossings cannot be derived</span>
            : <span className="t-ok">✓ every agent sits in one clock domain; no boundary to cross</span>,
      };
    }
    case 'access':
      return {
        left: [
          traffic ? `${traffic.nodes}×${traffic.nodes} measured matrix` : 'no matrix',
          traffic ? `${traffic.distinct_pairs} distinct pairs` : 'evaluate to populate',
          'permissions: no artifact',
        ],
        right: traffic
          ? <span className="t-ok">✓ counted from the trace of run {traffic.run_id.slice(0, 12)}</span>
          : <span className="t-warn">● no executed trace — the matrix stays empty</span>,
      };
    case 'floorplan': {
      const links = topology?.physical_links.length ?? 0;
      const routers = topology?.counts.routers ?? 0;
      const withLength = (topology?.physical_links ?? [])
        .filter((l) => l.length_mm != null).length;
      return {
        left: [
          topology ? `${routers} placed routers` : 'no placement',
          topology ? `${topology.counts.channels} directed channels` : '—',
          topology ? `${links} physical links` : '—',
        ],
        right: topology
          ? (withLength > 0
            ? <span className="t-ok">✓ placement from certified coordinates · {withLength} link lengths</span>
            : <span className="t-warn">● coordinates certified; this revision carries no link lengths</span>)
          : <span className="t-warn">● no certified placement</span>,
      };
    }
    case 'workload': {
      const p = parallelismOf(data);
      return {
        left: [
          data.design?.workload.model_family ?? 'no workload',
          p ? `TP=${p.tp} EP=${p.ep} PP=${p.pp}` : 'parallelism not carried',
          lowering ? `${lowering.totals.collectives} collectives` : 'no lowering',
        ],
        right: lowering
          ? <span className="t-ok">✓ lowering schedule {lowering.message_artifact_id.slice(0, 12)}</span>
          : <span className="t-warn">● no lowering artifact for this workload</span>,
      };
    }
    case 'simulation':
      return {
        left: [
          data.latestRun ? `run ${data.latestRun.run_id.slice(0, 12)}` : 'no run',
          data.latestRun?.status ?? 'NOT_RUN',
          traffic ? `${traffic.packets.toLocaleString()} packets counted` : 'no trace',
        ],
        right: data.latestRun
          ? <span className={data.latestRun.status === 'EVALUATED' ? 't-ok' : 't-warn'}>
              {data.latestRun.status === 'EVALUATED'
                ? `✓ executed by ${data.latestRun.backend ?? 'unknown backend'}`
                : '● no executed trace on this project'}
            </span>
          : <span className="t-warn">● evaluation has not run</span>,
      };
    default:
      return { left: [], right: null };
  }
}

export default function Loom({ projectId, view: viewParam }: {
  projectId: string;
  view: string;
}): ReactElement {
  const view: LoomViewId = isLoomView(viewParam) ? viewParam : 'topology';
  const data = useLoom(projectId);
  const status = statusFor(view, data);

  const body = ((): ReactElement => {
    switch (view) {
      case 'agents': return (
        <AgentsLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'catalog': return (
        <CatalogLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'domains': return (
        <DomainsLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'access': return (
        <AccessLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'floorplan': return (
        <FloorplanLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'workload': return (
        <WorkloadLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'simulation': return (
        <SimulationLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
      case 'topology':
      default: return (
        <TopologyLoom data={data} problems={<ProblemsPanel data={data} />} />
      );
    }
  })();

  return (
    <div className="loom">
      <div className="loom-head">
        <nav className="loom-tabs" aria-label="Loom views">
          {LOOM_VIEWS.map((v) => (
            <Link
              key={v.id}
              className={`loom-tab${view === v.id ? ' active' : ''}`}
              to={`/projects/${projectId}/loom/${v.id}`}
              title={v.label}
            >
              {v.label}
            </Link>
          ))}
        </nav>
        <div className="loom-ctx">
          <span className="context-label">REVISION</span>
          <code>{data.revisionId ?? 'none'}</code>
          <span className="context-label">DESIGN</span>
          <Hash value={data.design?.design_hash ?? null} />
          {data.dirty && <span className="stale">UNCOMPILED CHANGES</span>}
          <span className="context-label">PROJECT</span>
          <code>{projectId}</code>
        </div>
      </div>

      <div className="loom-body">{body}</div>

      {/* The footer is a landmark, not a live region: `role="status"` on a
          <footer> is the wrong role for the element. Only the verdict — the
          part that actually changes — is announced. */}
      <footer className="loom-status">
        <span className="loom-status-left">
          {status.left.filter(Boolean).map((part, i) => (
            <span key={i}>{part}</span>
          ))}
        </span>
        <span className="loom-status-right" role="status">{status.right}</span>
      </footer>
    </div>
  );
}
