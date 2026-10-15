/** Address map view (tracker M3-23 build the view, M3-24 holes/overlaps/unmapped).
 *
 *  Reads the LOCAL authoring graph — the same project.json document the fabric
 *  canvas edits — not a server artifact. Address windows are authored intent on
 *  agents and ports: there is no compiled decoder, no vendor IP and no physical
 *  placement behind them. Because the source is the workspace graph rather than
 *  a served artifact, values carry a plain source note instead of a `From`
 *  badge; the served provenance vocabulary has no word for a local document.
 */
import { useMemo, useState, type ReactElement } from 'react';
import { Link } from '../../studio';
import { analyzeAddressMap, hex, type AddressWindowRow } from '../../graph/addressMap';
import { useGraphStore } from '../../graph/store';
import { ExtensionPoint, Panes, SummaryStrip } from './parts';

/** A value section. Plain markup on purpose: `RailSection` pairs values with a
 *  served-artifact `From`, and this view's source is not a served artifact. */
function Panel({ title, note, children }: {
  title: string;
  note?: ReactElement | string;
  children: ReactElement | ReactElement[] | null;
}): ReactElement {
  return (
    <section className="loom-section">
      <h2 className="loom-section-title">{title}</h2>
      {note ? <p className="loom-from">{note}</p> : null}
      {children}
    </section>
  );
}

const SOURCE_NOTE = 'Source: this workspace’s authoring graph (project.json). '
  + 'Authored intent only — not a compiled decoder, not a vendor IP, not a placement.';

export default function AddressLoom({ projectId }: { projectId: string }): ReactElement {
  const store = useGraphStore('mesh-8x8', projectId);
  const report = useMemo(() => analyzeAddressMap(store.doc), [store.doc]);
  const [showAll, setShowAll] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const rows = showAll ? report.rows : report.mapped;
  const picked = selected ? report.rows.find((row) => row.key === selected) ?? null : null;

  const bytesOf = (value: bigint): string => `${hex(value)} (${value.toLocaleString()} B)`;

  const windowTable = (list: readonly AddressWindowRow[]): ReactElement => (
    <div className="loom-table-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>node</th>
            <th>agent / port</th>
            <th>base</th>
            <th>size</th>
            <th>end</th>
            <th>perm</th>
            <th className="num">addr width</th>
          </tr>
        </thead>
        <tbody>
          {list.map((row) => (
            <tr
              key={row.key}
              className={picked?.key === row.key ? 'sel' : undefined}
              onClick={() => setSelected(row.key)}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(row.key); }
              }}
            >
              <td><code>{row.nodeId}</code></td>
              <td><code>{row.agentId}/{row.portId}</code> <span className="muted">{row.role}</span></td>
              <td className="num"><code>{row.baseText}</code></td>
              <td className="num"><code>{row.sizeText}</code></td>
              <td className="num"><code>{hex(row.end)}</code></td>
              <td className="num">{row.permissions.join('/') || '—'}</td>
              <td className="num">
                {row.addressWidth}
                {row.exceedsWidth && <span className="t-bad" title="window does not fit the declared address width"> ⚠</span>}
              </td>
            </tr>
          ))}
          {list.length === 0 && (
            <tr><td colSpan={7} className="muted">No windows.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );

  return (
    <Panes
      left={
        <>
          <Panel title="Address map source" note={SOURCE_NOTE}>
            <p className="muted" style={{ fontSize: 12 }}>
              Edit windows in the fabric canvas inspector, then reopen this view.
              The map derives from the graph, so it updates as you author.
            </p>
            <Link className="link" to={`/projects/${projectId}/loom/graph`}>
              Open the fabric canvas to edit agents and windows →
            </Link>
          </Panel>

          <Panel title="Coverage">
            <p className="kv"><span>mapped bytes</span><span className="num">{hex(report.mappedBytes)}</span></p>
            <p className="kv"><span>span (first → last)</span><span className="num">{hex(report.spanBytes)}</span></p>
            <p className="kv"><span>uncovered (internal)</span><span className="num">{hex(report.uncoveredBytes)}</span></p>
            <p className="kv"><span>address widths</span><span className="num">{report.addressWidths.join(', ') || '—'}</span></p>
            <p className="kv"><span>nodes mapped</span><span className="num">{report.mappedNodes}</span></p>
            <p className="muted" style={{ fontSize: 12 }}>
              Holes are the gaps <em>between</em> mapped windows. The space before
              the first window and after the last is not counted.
            </p>
          </Panel>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Mapped windows', v: String(report.mapped.length), tone: 'info' },
            { k: 'Nodes mapped', v: String(report.mappedNodes) },
            { k: 'Overlaps', v: String(report.overlaps.length), tone: report.overlaps.length ? 'bad' : 'ok' },
            { k: 'Holes', v: String(report.holes.length), tone: report.holes.length ? 'warn' : 'ok' },
            { k: 'Unmapped initiators', v: String(report.unmappedInitiators.length), tone: report.unmappedInitiators.length ? 'warn' : 'ok' },
            { k: 'Malformed windows', v: String(report.malformed), tone: report.malformed ? 'bad' : undefined },
          ]} />

          {report.rows.length === 0 ? (
            <ExtensionPoint
              title="No authored address windows"
              needs="at least one agent port with an address window on the fabric canvas"
            />
          ) : (
            <>
              <Panel title="Windows">
                <label className="muted" style={{ fontSize: 12 }}>
                  <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
                  {' '}show initiator windows too (the map is drawn from target/bidirectional only)
                </label>
                {windowTable(rows)}
              </Panel>

              <Panel
                title="Overlaps"
                note="Two mapped windows that claim the same address. The project validator refuses these; the map lists each pair so it can be traced."
              >
                {report.overlaps.length === 0 ? (
                  <p className="muted">No two mapped windows overlap.</p>
                ) : (
                  <table className="tbl">
                    <thead>
                      <tr><th>a</th><th>b</th><th className="num">overlap</th></tr>
                    </thead>
                    <tbody>
                      {report.overlaps.map((o) => (
                        <tr key={`${o.a.key}~${o.b.key}`}>
                          <td><code>{o.a.nodeId}/{o.a.agentId}/{o.a.portId}</code></td>
                          <td><code>{o.b.nodeId}/{o.b.agentId}/{o.b.portId}</code></td>
                          <td className="num">{bytesOf(o.bytes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Panel>

              <Panel title="Internal holes">
                {report.holes.length === 0 ? (
                  <p className="muted">The mapped windows are contiguous.</p>
                ) : (
                  <table className="tbl">
                    <thead>
                      <tr><th>from</th><th>to</th><th className="num">bytes</th></tr>
                    </thead>
                    <tbody>
                      {report.holes.map((h) => (
                        <tr key={`${h.from}-${h.to}`}>
                          <td className="num"><code>{hex(h.from)}</code></td>
                          <td className="num"><code>{hex(h.to)}</code></td>
                          <td className="num">{hex(h.bytes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Panel>

              <Panel
                title="Unmapped initiator ports"
                note="An initiator or bidirectional port declared with no address window maps nothing, so it cannot originate addressed traffic. Reported, never repaired here."
              >
                {report.unmappedInitiators.length === 0 ? (
                  <p className="muted">Every initiator/bidirectional port maps at least one window.</p>
                ) : (
                  <table className="tbl">
                    <thead>
                      <tr><th>node</th><th>agent / port</th><th>role</th></tr>
                    </thead>
                    <tbody>
                      {report.unmappedInitiators.map((u) => (
                        <tr key={`${u.agentId}/${u.portId}`}>
                          <td><code>{u.nodeId}</code></td>
                          <td><code>{u.agentId}/{u.portId}</code></td>
                          <td>{u.role}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Panel>
            </>
          )}
        </div>
      }
      right={
        <Panel title="Window inspector">
          {picked ? (
            <>
              <p className="kv"><span>node</span><span className="num"><code>{picked.nodeId}</code></span></p>
              <p className="kv"><span>agent / port</span><span className="num"><code>{picked.agentId}/{picked.portId}</code></span></p>
              <p className="kv"><span>role</span><span className="num">{picked.role}</span></p>
              <p className="kv"><span>index</span><span className="num">{picked.index}</span></p>
              <p className="kv"><span>base</span><span className="num"><code>{picked.baseText}</code></span></p>
              <p className="kv"><span>size</span><span className="num"><code>{picked.sizeText}</code></span></p>
              <p className="kv"><span>end (exclusive)</span><span className="num"><code>{hex(picked.end)}</code></span></p>
              <p className="kv"><span>declared width</span><span className="num">{picked.addressWidth}</span></p>
              <p className="kv"><span>permissions</span><span className="num">{picked.permissions.join('/') || '—'}</span></p>
              {picked.exceedsWidth && (
                <p className="t-bad" role="alert">
                  This window does not fit its declared {picked.addressWidth}-bit address width.
                </p>
              )}
              <p className="muted" style={{ fontSize: 12 }}>
                Read from the authoring graph. Selecting here does not select a
                compiled object — authoring node ids are not certified router ids.
              </p>
            </>
          ) : (
            <p className="muted">Select a window in the map to read its interval.</p>
          )}
        </Panel>
      }
    />
  );
}
