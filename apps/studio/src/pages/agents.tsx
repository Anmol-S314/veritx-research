import { useMemo, useState, type ReactElement } from 'react';
import { api } from '../api';
import { AsyncView, useAsync } from '../studio';

/** One row of `request.agents` as the engine's frozen `Agent` dataclass emits it.
 *  These seven fields are the whole authored agent contract today — see
 *  veritx_dse/model/compile_model.py:200. Anything not listed here is either
 *  engine-derived or does not exist, and the panel below says which. */
interface AgentSpec {
  kind: string;
  count: number;
  data_width: number;
  addr_width: number;
  protocol: string;
  clock_domain: string | null;
  power_domain: string | null;
}

interface AgentRow extends AgentSpec {
  agent_id: string;
  index: number;
}

const ANY = 'ALL';

function uniq(values: (string | null)[]): string[] {
  return [...new Set(values.map((v) => v ?? '—'))].sort();
}

function csvCell(v: string | number | null): string {
  const s = v === null || v === undefined ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function AgentMatrix({ projectId }: { projectId: string }): ReactElement {
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const [kind, setKind] = useState<string>(ANY);
  const [protocol, setProtocol] = useState<string>(ANY);
  const [clock, setClock] = useState<string>(ANY);
  const [power, setPower] = useState<string>(ANY);

  const specs = useMemo<AgentSpec[]>(() => {
    const raw = draft.result.state === 'ready'
      ? (draft.result.data as unknown as { request?: { agents?: AgentSpec[] } })
      : null;
    return raw?.request?.agents ?? [];
  }, [draft.result]);

  const all = useMemo<AgentRow[]>(() => specs.flatMap((s) =>
    Array.from({ length: s.count }, (_, i) => ({
      ...s,
      agent_id: `${s.kind}_${i + 1}`,
      index: i + 1,
    }))), [specs]);

  const rows = useMemo(() => all.filter((r) =>
    (kind === ANY || r.kind === kind)
    && (protocol === ANY || r.protocol === protocol)
    && (clock === ANY || (r.clock_domain ?? '—') === clock)
    && (power === ANY || (r.power_domain ?? '—') === power)),
  [all, kind, protocol, clock, power]);

  const exportCsv = (): void => {
    const header = ['agent_id', 'kind', 'index', 'data_width', 'addr_width',
      'protocol', 'clock_domain', 'power_domain'];
    const body = rows.map((r) => [
      r.agent_id, r.kind, r.index, r.data_width, r.addr_width,
      r.protocol, r.clock_domain, r.power_domain,
    ].map(csvCell).join(','));
    const blob = new Blob([[header.join(','), ...body].join('\n')],
      { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${projectId}-agents.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const totals = useMemo(() => ({
    agents: all.length,
    kinds: specs.length,
    initiators: specs.filter((s) => s.protocol.toUpperCase().includes('AXI')).length,
  }), [all, specs]);

  return (
    <AsyncView result={draft.result} reload={draft.reload}>
      {() => (
      <div className="page">
        <h2>Agent matrix</h2>
        <p className="muted">
          Every agent instance in the current draft, expanded from the typed
          <code> request.agents</code> rows. Read-only: the authored agent
          contract is the engine's frozen <code>Agent</code> dataclass, so
          these values come from the draft and change on the Design page.
        </p>

        <div className="agent-stats">
          <div className="agent-stat"><b className="num">{totals.agents}</b><span>agent instances</span></div>
          <div className="agent-stat"><b className="num">{totals.kinds}</b><span>agent kinds</span></div>
          <div className="agent-stat"><b className="num">{totals.initiators}</b><span>AXI kinds</span></div>
        </div>

        <div className="segmented" role="group" aria-label="Filter agents">
          <label className="agent-filter">
            Kind
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value={ANY}>All</option>
              {uniq(all.map((r) => r.kind)).map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
          <label className="agent-filter">
            Protocol
            <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
              <option value={ANY}>All</option>
              {uniq(all.map((r) => r.protocol)).map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
          <label className="agent-filter">
            Clock
            <select value={clock} onChange={(e) => setClock(e.target.value)}>
              <option value={ANY}>All</option>
              {uniq(all.map((r) => r.clock_domain)).map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
          <label className="agent-filter">
            Power
            <select value={power} onChange={(e) => setPower(e.target.value)}>
              <option value={ANY}>All</option>
              {uniq(all.map((r) => r.power_domain)).map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
        </div>

        <p>
          <button
            className="btn"
            onClick={exportCsv}
            disabled={rows.length === 0}
          >
            Export CSV ({rows.length})
          </button>
        </p>

        <table className="live-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Kind</th>
              <th className="num">#</th>
              <th className="num">Data width</th>
              <th className="num">Addr width</th>
              <th>Protocol</th>
              <th>Clock domain</th>
              <th>Power domain</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.agent_id}>
                <td><strong>{r.agent_id}</strong></td>
                <td>{r.kind}</td>
                <td className="num">{r.index}</td>
                <td className="num">{r.data_width}</td>
                <td className="num">{r.addr_width}</td>
                <td>{r.protocol}</td>
                <td>{r.clock_domain ?? <span className="muted">unset</span>}</td>
                <td>{r.power_domain ?? <span className="muted">unset</span>}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={8} className="muted">No agents match these filters.</td></tr>
            )}
          </tbody>
        </table>

        <h3>What this matrix cannot show</h3>
        <p className="muted">
          Named rather than faked. The authored contract is
          seven fields; everything below is either derived by the engine or
          absent from the model, so there is no value to render here.
        </p>
        <table className="live-table">
          <thead>
            <tr><th>Attribute</th><th>State</th><th>Authority</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Routing, turn restrictions, VC map</td>
              <td><span className="muted">engine-derived</span></td>
              <td className="muted">PRD §4.4 — LOCKED, no override</td>
            </tr>
            <tr>
              <td>AIU type, sideband, access perms, connected targets</td>
              <td><span className="muted">not in the model</span></td>
              <td className="muted">requires an engine contract change</td>
            </tr>
            <tr>
              <td>Buffer depth, max outstanding, ordering, splitting</td>
              <td><span className="muted">not in the model</span></td>
              <td className="muted">requires an engine contract change</td>
            </tr>
            <tr>
              <td>Clock / power domain defaults</td>
              <td><span className="muted">per-agent, unset</span></td>
              <td className="muted">falls back to PhysicalContext</td>
            </tr>
          </tbody>
        </table>
      </div>
      )}
    </AsyncView>
  );
}