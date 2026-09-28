import { useState, type ReactElement } from 'react';
import type { FabricGroup, MappingGroup, MappingRow } from '../../api';
import { fmtNum, humanize } from '../badges';
import { EmptyState } from './EmptyState';
import { useSelection } from './selection';

/** Mapping inspector: search / agent filter / idle-only preserved; clicking
 * a rank selects it — endpoint, router, coordinates and fabric highlight
 * follow through the shared selection context. */
export default function MappingInspector({ group, fabric, onJump }: {
  group: MappingGroup;
  fabric: FabricGroup;
  onJump: (tab: string) => void;
}): ReactElement {
  const [filter, setFilter] = useState('');
  const [agentFilter, setAgentFilter] = useState('');
  const [idleOnly, setIdleOnly] = useState(false);
  const { selection, select } = useSelection();
  const needle = filter.trim().toLowerCase();
  const kinds = [...new Set(group.rows.map((r) => r.agent_kind ?? ''))]
    .filter(Boolean).sort();
  const rows = group.rows.filter((row) => {
    if (agentFilter && row.agent_kind !== agentFilter) return false;
    if (!needle) return true;
    const coords = row.coordinates
      ? `tp${row.coordinates.tp} pp${row.coordinates.pp} `
        + `ep${row.coordinates.ep} dp${row.coordinates.dp}`
      : '';
    return String(row.rank).includes(needle)
      || (row.agent_kind ?? '').toLowerCase().includes(needle)
      || String(row.instance_index ?? '').includes(needle)
      || coords.toLowerCase().includes(needle);
  });
  const idle = group.idle_agents;
  const selected: MappingRow | null =
    selection.kind === 'rank' || selection.kind === 'endpoint'
      ? (group.rows.find((r) => r.rank === selection.id
        || r.endpoint_id === selection.id) ?? null)
      : null;
  const selectedRouter = selected?.endpoint_id != null
    ? fabric.topology?.endpoints.find(
      (e) => e.endpoint_id === selected.endpoint_id)?.router_id ?? null
    : null;

  if (!group.available || group.rows.length === 0) {
    return (
      <section className="card">
        <h4>Mapping</h4>
        <EmptyState title="No rank mapping exists for this design.">
          <p>The workload declares no mapped ranks, so there is nothing to
          place on the fabric.</p>
        </EmptyState>
      </section>
    );
  }

  return (
    <section className="card">
      <div className="inspector-head">
        <h4>Mapping</h4>
        <input
          className="inspector-filter"
          placeholder="search rank, coordinate, agent or instance…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Search mapping rows"
        />
      </div>
      <div className="inspector-controls">
        <label>agent
          <select value={agentFilter}
                  onChange={(e) => setAgentFilter(e.target.value)}>
            <option value="">all</option>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={idleOnly}
                  onChange={(e) => setIdleOnly(e.target.checked)} />
          idle agents only
        </label>
      </div>
      {group.parallelism && (
        <p className="muted">
          parallelism TP{group.parallelism.tp}/PP{group.parallelism.pp}/
          EP{group.parallelism.ep}/DP{group.parallelism.dp} ·{' '}
          {group.rank_count} ranks
        </p>
      )}
      {!idleOnly && (
        <>
          {rows.length === 0 ? (
            <EmptyState title="No rows match this filter.">
              <p>Clear the search or agent filter to see the full mapping.</p>
            </EmptyState>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>rank</th><th>tp</th><th>pp</th><th>ep</th><th>dp</th>
                  <th>agent</th><th>group</th><th>instance</th><th>endpoint</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const isSel = selected !== null
                    && row.rank === selected.rank
                    && row.endpoint_id === selected.endpoint_id;
                  return (
                    <tr key={`${row.rank}-${row.endpoint_id}`}
                        className={isSel ? 'row-selected' : ''}
                        onClick={() => select(
                          row.rank != null
                            ? { kind: 'rank', id: row.rank,
                                secondary: row.endpoint_id }
                            : { kind: 'endpoint',
                                id: row.endpoint_id ?? -1 })}
                        style={{ cursor: 'pointer' }}>
                      <td className="num">{row.rank}</td>
                      <td className="num">{row.coordinates?.tp ?? '—'}</td>
                      <td className="num">{row.coordinates?.pp ?? '—'}</td>
                      <td className="num">{row.coordinates?.ep ?? '—'}</td>
                      <td className="num">{row.coordinates?.dp ?? '—'}</td>
                      <td>{humanize(row.agent_kind ?? '—')}</td>
                      <td className="num">{row.group_index}</td>
                      <td className="num">{row.instance_index}</td>
                      <td className="num">{row.endpoint_id}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <p className="muted">
            {rows.length} of {group.rows.length} rows · ⓘ derived · no editing
          </p>
        </>
      )}
      {selected && (
        <div className="inspector-detail">
          <h5 className="inspector-label">Selected rank {selected.rank}</h5>
          <div className="kv-grid">
            <div className="kv"><span>agent</span>
              <span>{humanize(selected.agent_kind ?? '—')} #
              {selected.instance_index}</span></div>
            <div className="kv"><span>endpoint</span>
              <span className="num">{selected.endpoint_id ?? '—'}</span></div>
            <div className="kv"><span>router</span>
              <span className="num">{selectedRouter ?? '—'}</span></div>
            <div className="kv"><span>coordinates</span>
              <span className="num">
                {selected.coordinates
                  ? `tp${selected.coordinates.tp} pp${selected.coordinates.pp} `
                    + `ep${selected.coordinates.ep} dp${selected.coordinates.dp}`
                  : '—'}
              </span></div>
          </div>
          <div className="form-row">
            <button className="btn btn-small"
                    onClick={() => {
                      if (selected.endpoint_id != null) {
                        select({ kind: 'endpoint',
                                 id: selected.endpoint_id });
                      }
                      onJump('fabric');
                    }}>
              Highlight on Fabric →
            </button>
          </div>
        </div>
      )}
      {idle && idle.count > 0 && (
        <>
          <h5 className="inspector-label">Idle attached agents</h5>
          <p className="muted">
            {idle.count} of {idle.attached} attached agents are not mapped to
            a rank. That is a design fact — the fabric is larger than the
            workload needs.
          </p>
          <table className="tbl">
            <thead><tr><th>agent</th><th>attached</th></tr></thead>
            <tbody>
              {Object.entries(idle.by_kind).map(([kind, count]) => (
                <tr key={kind}>
                  <td>{humanize(kind)}</td>
                  <td className="num">{fmtNum(count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
