import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
import { Link } from '../../studio';
import { baseDocument } from '../../canonicalDraft';
import { Hash } from '../../components/badges';
import {
  agentRows, declaredScope, type AgentRow, type AgentScope, type LoomData,
} from './data';
import type { AgentField } from './draftCommands';
import type { DraftStore } from './draftStore';
import {
  agentId, loomIdText, pickId, type AgentId,
} from './selection';
import type { LoomSelectionStore } from './selectionStore';
import { ExtensionPoint, Kv, Panes, RailSection, From, SummaryStrip } from './parts';
import { NodeTable, useAuthoring } from './authoring';

const ANY = 'ALL';

/** Columns a dense fabric matrix usually carries that neither the authored
 *  agent contract nor the certified attachment provides. Listed, never
 *  filled in. */
const NOT_IN_CONTRACT: { field: string; needs: string }[] = [
  { field: 'Max outstanding transactions', needs: 'a per-agent credit/QoS record in the engine' },
  { field: 'Ordering rules', needs: 'a per-agent ordering model in the engine' },
  { field: 'Payload splitting', needs: 'a flit-packing record per agent' },
  { field: 'Base address / access', needs: 'the address-map artifact (see I–T mapping)' },
  { field: 'AIU type / sideband', needs: 'an interface-unit record per agent' },
];

type SortKey =
  | 'endpointId' | 'label' | 'kind' | 'groupIndex' | 'instanceIndex'
  | 'routerId' | 'portId' | 'dataWidth' | 'addrWidth' | 'protocol'
  | 'clockDomain' | 'powerDomain';

interface Column {
  key: SortKey;
  label: string;
  numeric: boolean;
}

const COLUMNS: Column[] = [
  { key: 'label', label: 'agent', numeric: false },
  { key: 'kind', label: 'kind', numeric: false },
  { key: 'endpointId', label: 'endpoint', numeric: true },
  { key: 'groupIndex', label: 'group', numeric: true },
  { key: 'instanceIndex', label: 'instance', numeric: true },
  { key: 'routerId', label: 'router', numeric: true },
  { key: 'portId', label: 'port', numeric: true },
  { key: 'dataWidth', label: 'data width', numeric: true },
  { key: 'addrWidth', label: 'addr width', numeric: true },
  { key: 'protocol', label: 'protocol', numeric: false },
  { key: 'clockDomain', label: 'clock domain', numeric: false },
  { key: 'powerDomain', label: 'power domain', numeric: false },
];

function cell(row: AgentRow, key: SortKey): string | number | null {
  return row[key];
}

function compare(a: AgentRow, b: AgentRow, key: SortKey): number {
  const x = cell(a, key);
  const y = cell(b, key);
  if (x == null && y == null) return 0;
  if (x == null) return 1;
  if (y == null) return -1;
  if (typeof x === 'number' && typeof y === 'number') return x - y;
  return String(x).localeCompare(String(y));
}

function csvCell(v: string | number | null): string {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function uniq(values: (string | null)[]): string[] {
  return [...new Set(values.map((v) => v ?? '—'))].sort();
}

export default function AgentsLoom({ data, sel, draftStore, problems }: {
  data: LoomData;
  sel: LoomSelectionStore;
  draftStore: DraftStore;
  problems?: ReactNode;
}): ReactElement {
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState(ANY);
  const [protocol, setProtocol] = useState(ANY);
  const [clock, setClock] = useState(ANY);
  const [power, setPower] = useState(ANY);
  const [seat, setSeat] = useState<string>(ANY);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({
    key: 'endpointId', dir: 1,
  });
  const [hidden, setHidden] = useState<SortKey[]>([]);
  const authoring = useAuthoring(data.projectId);

  const rows = useMemo(() => agentRows(data), [data]);
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;
  const groups = data.agents;
  const scope = useMemo(() => declaredScope(data), [data]);
  const declaredRows = useMemo(
    () => rows.filter((r) => r.scope === 'ATTACHED' || r.scope === 'UNATTACHED'),
    [rows],
  );
  const orphanRows = useMemo(
    () => rows.filter((r) => r.scope === 'ORPHAN_ARTIFACT' || r.scope === 'INTEGRITY_ERROR'),
    [rows],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matched = rows.filter((r) =>
      (kind === ANY || r.kind === kind)
      && (protocol === ANY || (r.protocol ?? '—') === protocol)
      && (clock === ANY || (r.clockDomain ?? '—') === clock)
      && (power === ANY || (r.powerDomain ?? '—') === power)
      && (seat === ANY || (seat as AgentScope) === r.scope)
      && (q === '' || r.label.toLowerCase().includes(q)
        || String(r.endpointId).includes(q)
        || String(r.routerId ?? '').includes(q)));
    return matched.sort((a, b) => compare(a, b, sort.key) * sort.dir);
  }, [rows, search, kind, protocol, clock, power, seat, sort]);

  const columns = COLUMNS.filter((c) => !hidden.includes(c.key));

  // An agent is keyed by the compiler's (group, instance) pair rather than by
  // an `endpoint_id`, so the selection survives a recompile that renumbers the
  // attachment — and it resolves for a declared agent that has no seat at all.
  const chosen = pickId(sel.selection, 'agent');
  const pick = chosen
    ? rows.find((r) => (
      r.groupIndex === chosen.groupIndex && r.instanceIndex === chosen.instanceIndex
    )) ?? null
    : null;
  const isHeld = (r: AgentRow): boolean => (
    chosen != null
    && r.groupIndex === chosen.groupIndex
    && r.instanceIndex === chosen.instanceIndex
  );
  const idOfRow = (r: AgentRow): AgentId => agentId(r.groupIndex, r.instanceIndex);

  const attached = rows.filter((r) => r.attached).length;
  const seatless = topology
    ? topology.counts.seats - topology.counts.endpoints
    : null;

  const toggleSort = (key: SortKey): void => setSort((current) => (
    current.key === key
      ? { key, dir: current.dir === 1 ? -1 : 1 }
      : { key, dir: 1 }
  ));

  const exportCsv = (): void => {
    const header = [...columns.map((c) => c.key), 'scope'];
    const body = filtered.map((r) => header
      .map((k) => (k === 'scope' ? csvCell(r.scope) : csvCell(cell(r, k as SortKey))))
      .join(','));
    const blob = new Blob([[header.join(','), ...body].join('\n')],
      { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.projectId}-agents.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Search"
            note="Matches the machine identity, the endpoint id or the router it is seated on."
          >
            <label className="loom-field">
              <span>agent / endpoint / router</span>
              <input
                id="loom-agent-search"
                name="agent-search"
                type="search"
                value={search}
                placeholder="compute_tile_0_3, 12, 40"
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
          </RailSection>

          <RailSection
            title="Filters"
            note="Filters cover authored and certified fields only — every option is a value that exists on this revision."
          >
            <label className="loom-field">
              <span>attachment scope</span>
              <select value={seat} onChange={(e) => setSeat(e.target.value)}>
                <option value={ANY}>all agents</option>
                <option value="ATTACHED">attached — declared and seated</option>
                <option value="UNATTACHED">unattached — declared, no seat</option>
                <option value="ORPHAN_ARTIFACT">orphan artifact — seated, not declared</option>
                <option value="INTEGRITY_ERROR">integrity error — contradictory seat</option>
              </select>
            </label>
            <label className="loom-field">
              <span>kind</span>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value={ANY}>all kinds</option>
                {uniq(rows.map((r) => r.kind)).map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>
            <label className="loom-field">
              <span>protocol</span>
              <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
                <option value={ANY}>all protocols</option>
                {uniq(rows.map((r) => r.protocol)).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <label className="loom-field">
              <span>clock domain</span>
              <select value={clock} onChange={(e) => setClock(e.target.value)}>
                <option value={ANY}>all domains</option>
                {uniq(rows.map((r) => r.clockDomain)).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="loom-field">
              <span>power domain</span>
              <select value={power} onChange={(e) => setPower(e.target.value)}>
                <option value={ANY}>all domains</option>
                {uniq(rows.map((r) => r.powerDomain)).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
          </RailSection>

          <RailSection title="Columns">
            <ul className="loom-checks">
              {COLUMNS.map((c) => (
                <li key={c.key} className={hidden.includes(c.key) ? 'off' : 'on'}>
                  <input
                    type="checkbox"
                    id={`col-${c.key}`}
                    checked={!hidden.includes(c.key)}
                    onChange={() => setHidden((current) => (
                      current.includes(c.key)
                        ? current.filter((k) => k !== c.key)
                        : [...current, c.key]
                    ))}
                  />
                  <label htmlFor={`col-${c.key}`}>{c.label}</label>
                </li>
              ))}
            </ul>
            <p className="loom-note">
              Every column is read from the certified attachment or the authored
              group record. Hiding one removes it from the table and the CSV.
            </p>
          </RailSection>

          <RailSection title="Declared groups">
            <From
              origin="AUTHORED"
              artifact="draft"
              note="declared counts; seated counts are DERIVED · attachment"
              data={data}
            />
            <table className="tbl">
              <thead>
                <tr><th>kind</th><th className="num">declared</th><th className="num">seated</th></tr>
              </thead>
              <tbody>
                {groups.map((g, i) => {
                  const declared = g.count;
                  const seatedCount = rows.filter(
                    (r) => r.groupIndex === i && r.attached,
                  ).length;
                  return (
                    <tr key={g.kind}>
                      <td><code>{g.kind}</code></td>
                      <td className="num">{declared}</td>
                      <td className="num">{seatedCount}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {groups.length === 0 && (
              <p className="muted">The draft carries no agents block yet.</p>
            )}
          </RailSection>

          <RailSection
            title="Graph node table (beta)"
            note="Rows are the local authoring graph's nodes, not certified agent seats. Batch VC and CSV edit the graph only."
          >
            <NodeTable store={authoring} />
          </RailSection>

          <RailSection title="Not in the contract">
            <ul className="loom-needs">
              {NOT_IN_CONTRACT.map((f) => (
                <li key={f.field}><b>{f.field}</b> — requires {f.needs}</li>
              ))}
            </ul>
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          {scope.dirty && topology && (
            <p className="warn" role="status">
              The draft has uncompiled changes, so two declaration scopes are
              on screen: the rows below expand the <b>current draft</b> ({scope.draftTotal} instance(s)),
              while the topology belongs to <b>revision {scope.revisionId?.slice(0, 12) ?? '?'}</b> as compiled
              {scope.revisionTotal != null && (
                <> ({scope.revisionTotal} instance(s){scope.revisionGroups && ` — ${scope.revisionGroups.map((g) => `${g.count}×${g.kind}`).join(', ')}`})</>
              )}.
              A mismatch reads as two scopes, not a corrupt join.
            </p>
          )}
          <SummaryStrip items={[
            { k: 'Declared', v: String(declaredRows.length), tone: 'info' },
            { k: 'Seated', v: topology ? String(attached) : 'no topology' },
            { k: 'Unseated', v: topology ? String(declaredRows.length - attached) : '—' },
            { k: 'Orphan / integrity', v: orphanRows.length ? String(orphanRows.length) : '0', tone: orphanRows.length ? 'bad' : undefined },
            { k: 'Declared groups', v: String(groups.length) },
            { k: 'Protocols', v: String(uniq(rows.map((r) => r.protocol)).length) },
            { k: 'Clock domains', v: String(uniq(rows.map((r) => r.clockDomain)).length) },
            { k: 'Shown', v: `${filtered.length} of ${rows.length}` },
          ]} />

          <div className="loom-actions">
            <button
              type="button"
              className="btn"
              disabled={filtered.length === 0}
              onClick={exportCsv}
            >
              Export CSV ({filtered.length})
            </button>
            {topology && seatless != null && seatless > 0 && (
              <Link className="btn" to={`/projects/${data.projectId}/loom/topology`}>
                {seatless} unused seat{seatless === 1 ? '' : 's'} on this fabric
              </Link>
            )}
          </div>

          {rows.length === 0 ? (
            <ExtensionPoint
              title="No agents on this project"
              needs="an agents block on the project draft"
            />
          ) : (
            <div className="loom-table-wrap">
              <table className="tbl loom-table">
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th
                        key={c.key}
                        className={c.numeric ? 'num' : undefined}
                        aria-sort={sort.key === c.key
                          ? (sort.dir === 1 ? 'ascending' : 'descending')
                          : 'none'}
                      >
                        <button
                          type="button"
                          className="loom-sort"
                          onClick={() => toggleSort(c.key)}
                        >
                          {c.label}
                          {sort.key === c.key && (
                            <span aria-hidden="true">{sort.dir === 1 ? ' ▲' : ' ▼'}</span>
                          )}
                        </button>
                      </th>
                    ))}
                    <th>seat</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r) => (
                    <tr
                      key={`${r.endpointId}-${r.label}`}
                      className={isHeld(r) ? 'sel' : undefined}
                      onClick={() => sel.select(idOfRow(r))}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          sel.select(idOfRow(r));
                        }
                      }}
                    >
                      {columns.map((c) => (
                        <td
                          key={c.key}
                          className={c.numeric ? 'num' : undefined}
                        >
                          {renderCell(cell(r, c.key), c.key)}
                        </td>
                      ))}
                      <td title={r.integrityNote ?? undefined}>
                        {r.scope === 'ATTACHED' && <span className="t-ok">attached</span>}
                        {r.scope === 'UNATTACHED' && <span className="muted">unattached</span>}
                        {r.scope === 'ORPHAN_ARTIFACT' && <span className="t-warn">orphan artifact</span>}
                        {r.scope === 'INTEGRITY_ERROR' && <span className="t-bad">integrity error</span>}
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={columns.length + 1} className="muted">
                        No agent matches these filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      }
      right={
        <>
          <RailSection title="Agent inspector">
            {pick ? (
              <>
                <GroupEditor data={data} store={draftStore}
                  groupIndex={pick.groupIndex} />
                <From
                  origin="DERIVED"
                  artifact="attachment"
                  data={data}
                />
                <Kv label="agent" value={<code>{pick.label}</code>} />
                <Kv label="selection id" value={<code>{loomIdText(agentId(pick.groupIndex, pick.instanceIndex))}</code>} />
                <Kv label="endpoint id" value={pick.endpointId < 0 ? '—' : String(pick.endpointId)} mono />
                <Kv label="kind" value={pick.kind} />
                <Kv label="group index" value={String(pick.groupIndex)} mono />
                <Kv label="instance index" value={String(pick.instanceIndex)} mono />
                <Kv label="router" value={pick.routerId != null ? `R${pick.routerId}` : '—'} mono />
                <Kv label="port" value={pick.portId != null ? String(pick.portId) : '—'} mono />
                <Kv label="scope" value={
                  <span className={pick.scope === 'ATTACHED' ? 't-ok' : pick.scope === 'UNATTACHED' ? 'muted' : pick.scope === 'ORPHAN_ARTIFACT' ? 't-warn' : 't-bad'}>
                    {pick.scope}
                  </span>
                } />
                {pick.integrityNote && (
                  <p className="bad" role="alert">{pick.integrityNote}</p>
                )}
                <p className="loom-note">
                  Endpoint id, router and port are certified attachment facts.
                  Widths, protocol and domains are the authored fields of group{' '}
                  <code>{pick.groupIndex}</code>, read verbatim from the draft.
                  The selection id is the group/instance pair the compiler itself
                  keys on, so it still resolves after a recompile renumbers the
                  endpoint ids.
                </p>
                <h4 className="loom-subhead">Interface</h4>
                <From
                  origin="AUTHORED"
                  artifact="draft"
                  data={data}
                />
                <Kv label="data width" value={pick.dataWidth != null ? `${pick.dataWidth} bits` : '—'} mono />
                <Kv label="addr width" value={pick.addrWidth != null ? `${pick.addrWidth} bits` : '—'} mono />
                <Kv label="protocol" value={pick.protocol ?? '—'} />
                <Kv label="clock domain" value={pick.clockDomain ?? <span className="muted">undeclared</span>} />
                <Kv label="power domain" value={pick.powerDomain ?? <span className="muted">undeclared</span>} />
                <p className="loom-note">
                  An undeclared domain is not the same as a single domain — the
                  Domains view shows what the crossing analysis can and cannot
                  say about it.
                </p>
              </>
            ) : (
              <p className="muted">Select a row to inspect its record.</p>
            )}
          </RailSection>

          <RailSection
            title="Attachment"
            note="Which declared agent the compiler placed on which router — materialized fact, not intent."
          >
            <From
              origin="DERIVED"
              artifact="attachment"
              data={data}
            />
            {topology ? (
              <>
                <Kv label="endpoints / seats" value={`${topology.counts.endpoints} / ${topology.counts.seats}`} mono />
                <Kv label="routers" value={String(topology.counts.routers)} mono />
                <Kv label="attachment" value={<Hash value={topology.attachment_hash} />} />
              </>
            ) : (
              <ExtensionPoint
                title="No certified attachment"
                needs="a compiled revision. Seating is what the compiler decides, so the rows above are declared intent only."
              />
            )}
          </RailSection>

          {problems}
        </>
      }
    />
  );
}

/** The authoring surface for ONE agent group: the draft mutation seam made
 *  visible. Every input maps to exactly one canonical field of the engine's
 *  Agent record; typing runs a typed command against the local working copy;
 *  Save hands the whole document to the server's validated PUT. Nothing here
 *  computes a design hash, decides legality, or writes JSON directly. */
function GroupEditor({ data, store, groupIndex }: {
  data: LoomData;
  store: DraftStore;
  groupIndex: number;
}): ReactElement {
  const { reloadDraft } = data;

  const doc = store.doc ?? data.draftRequest;
  const base = doc ? baseDocument(doc) : null;
  const agents = base && Array.isArray(base.agents) ? base.agents : [];
  const group = (agents[groupIndex] ?? null) as Record<string, unknown> | null;

  const [pending, setPending] = useState<string | null>(null);

  if (!group) {
    return <p className="muted">The draft declares no group {groupIndex}.</p>;
  }

  const edit = (field: AgentField, value: number | string | null): void => {
    const outcome = store.run({ type: 'set_agent_field', group: groupIndex,
                                field, value });
    setPending(outcome.refused); // null on success → clears previous refusal
  };

  const num = (field: AgentField): string => {
    const v = group[field];
    return typeof v === 'number' ? String(v) : '';
  };
  const txt = (field: AgentField): string => {
    const v = group[field];
    return typeof v === 'string' ? v : '';
  };

  const save = async (): Promise<void> => {
    const ok = await store.save();
    if (ok) reloadDraft();
  };

  return (
    <div className="loom-editor" role="group"
         aria-label={`Edit agent group ${groupIndex}`}>
      <p className="loom-note">
        Edits mutate the <b>draft</b> through typed commands; the server
        re-validates the whole document on save. A compiled revision is never
        touched — save, then compile to mint a new one.
      </p>

      <label className="loom-field">
        <span>kind</span>
        <input
          type="text"
          value={typeof group.kind === 'string' ? group.kind : ''}
          onChange={(e) => {
            const outcome = store.run({ type: 'set_agent_kind', group: groupIndex,
                                        value: e.target.value });
            setPending(outcome.refused);
          }}
        />
      </label>

      <label className="loom-field">
        <span>count</span>
        <input
          type="number"
          min={1}
          value={num('count')}
          onChange={(e) => edit('count', Number(e.target.value))}
        />
      </label>

      <label className="loom-field">
        <span>data width (bits)</span>
        <input
          type="number"
          min={8}
          step={8}
          value={num('data_width')}
          onChange={(e) => edit('data_width', Number(e.target.value))}
        />
      </label>

      <label className="loom-field">
        <span>addr width (bits)</span>
        <input
          type="number"
          min={8}
          step={8}
          value={num('addr_width')}
          onChange={(e) => edit('addr_width', Number(e.target.value))}
        />
      </label>

      <label className="loom-field">
        <span>protocol</span>
        <input
          type="text"
          value={txt('protocol')}
          onChange={(e) => edit('protocol', e.target.value)}
        />
      </label>

      <label className="loom-field">
        <span>clock domain (empty = undeclared)</span>
        <input
          type="text"
          value={txt('clock_domain')}
          placeholder="undeclared"
          onChange={(e) => edit('clock_domain', e.target.value || null)}
        />
      </label>

      <label className="loom-field">
        <span>power domain (empty = undeclared)</span>
        <input
          type="text"
          value={txt('power_domain')}
          placeholder="undeclared"
          onChange={(e) => edit('power_domain', e.target.value || null)}
        />
      </label>

      <div className="loom-actions">
        <button
          type="button"
          className="btn"
          disabled={!store.dirty || store.saving}
          onClick={() => { void save(); }}
        >
          {store.saving ? 'Saving…' : 'Save draft'}
        </button>
        <button type="button" className="btn" disabled={!store.canUndo}
                onClick={store.undo}>
          Undo
        </button>
        <button type="button" className="btn" disabled={!store.canRedo}
                onClick={store.redo}>
          Redo
        </button>
        {store.dirty && <span className="stale">UNSAVED</span>}
      </div>

      {(pending ?? store.error) && (
        <p className="bad" role="alert">{pending ?? store.error}</p>
      )}
      {!store.dirty && !pending && (
        <p className="muted">Working copy matches the server draft.</p>
      )}
    </div>
  );
}

function renderCell(value: string | number | null, key: SortKey) {
  if (value == null) return <span className="muted">—</span>;
  if (key === 'label' || key === 'protocol'
    || key === 'clockDomain' || key === 'powerDomain' || key === 'kind') {
    return <code>{value}</code>;
  }
  return value;
}