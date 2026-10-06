import { useMemo, useState, type ReactElement, type ReactNode } from 'react';
import { Link } from '../../studio';
import { Hash } from '../../components/badges';
import {
  domainsOf, type Crossing, type DomainRow, type LoomData,
} from './data';
import { channelId, domainId, pickId } from './selection';
import type { LoomSelectionStore } from './selectionStore';
import { ExtensionPoint, Kv, Panes, RailSection, SummaryStrip } from './parts';

/** A domain the author declared. Names come from the draft; there is no
 *  registry of legal domain names, so nothing here can be invalid — only
 *  undeclared. */
const CLOCK = 'clock' as const;
const POWER = 'power' as const;

export default function DomainsLoom({ data, sel, problems }: {
  data: LoomData;
  sel: LoomSelectionStore;
  problems?: ReactNode;
}): ReactElement {
  const [view, setView] = useState<'domains' | 'crossings'>('domains');

  const { rows, crossings, routersWithoutAgents } = useMemo(
    () => domainsOf(data), [data],
  );

  const clockRows = rows.filter((r) => r.kind === CLOCK);
  const powerRows = rows.filter((r) => r.kind === POWER);
  const declared = rows.filter((r) => r.id !== 'undeclared');
  const undeclared = rows.filter((r) => r.id === 'undeclared');
  const crossingPairs = useMemo(() => {
    const set = new Set<string>();
    for (const c of crossings) set.add(`${c.srcDomain} → ${c.dstDomain}`);
    return [...set].sort();
  }, [crossings]);

  const chosen = pickId(sel.selection, 'domain');
  const pick = chosen
    ? rows.find((r) => r.kind === chosen.axis && r.id === chosen.domain) ?? null
    : null;
  // A crossing is not a row in any table, so the crossing list selects the
  // CHANNEL that crosses — a canonical topology object — rather than a
  // boundary key that only exists in this view.
  const heldChannel = pickId(sel.selection, 'channel');
  const heldCrossing = heldChannel
    ? crossings.find((c) => c.channelId === heldChannel.channelId) ?? null
    : null;
  const pickCrossings = heldCrossing
    ? crossings.filter((c) => crossingKey(c) === crossingKey(heldCrossing))
    : [];

  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;

  const table = (kind: 'clock' | 'power', list: DomainRow[]): ReactElement => (
    <table className="tbl">
      <thead>
        <tr>
          <th>domain</th>
          <th className="num">agents</th>
          <th className="num">seated</th>
          <th className="num">routers</th>
          <th>state</th>
        </tr>
      </thead>
      <tbody>
        {list.map((r) => (
          <tr
            key={`${r.kind}:${r.id}`}
            className={chosen?.axis === r.kind && chosen.domain === r.id ? 'sel' : undefined}
            onClick={() => sel.select(domainId(r.kind, r.id))}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                sel.select(domainId(r.kind, r.id));
              }
            }}
          >
            <td>
              {r.id === 'undeclared'
                ? <span className="muted">undeclared</span>
                : <code>{r.id}</code>}
            </td>
            <td className="num">{r.agentCount}</td>
            <td className="num">{r.attachedCount}</td>
            <td className="num">{r.routers.length}</td>
            <td>
              <span className={`t-${r.id === 'undeclared' ? 'warn' : 'ok'}`}>
                {r.id === 'undeclared' ? 'no assignment' : 'declared'}
              </span>
            </td>
          </tr>
        ))}
        {list.length === 0 && (
          <tr>
            <td colSpan={5} className="muted">
              No agents on this project, so no {kind} assignment exists.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );

  return (
    <Panes
      left={
        <>
          <RailSection
            title="Domain sources"
            note="Two facts, kept apart: the domain name is authored intent on the draft; which agents and routers carry it is read off the certified attachment."
          >
            <Kv label="clock domains declared" value={String(declared.filter((r) => r.kind === CLOCK).length)} mono />
            <Kv label="power domains declared" value={String(declared.filter((r) => r.kind === POWER).length)} mono />
            <Kv label="agents unassigned" value={String(undeclared.reduce((n, r) => n + r.agentCount, 0))} mono />
            <Kv label="routers with no agent" value={String(routersWithoutAgents)} mono />
            <Kv label="topology" value={topology ? <Hash value={topology.attachment_hash} /> : '—'} />
          </RailSection>

          <RailSection
            title="Views"
            note="The crossing list is derived: certified seating × authored domain names."
          >
            <div className="segmented" role="tablist" aria-label="Domain view">
              <button
                type="button"
                role="tab"
                aria-selected={view === 'domains'}
                className={view === 'domains' ? 'selected' : ''}
                onClick={() => setView('domains')}
              >
                Domain census
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === 'crossings'}
                className={view === 'crossings' ? 'selected' : ''}
                onClick={() => setView('crossings')}
              >
                Clock crossings ({crossings.length})
              </button>
            </div>
          </RailSection>

          <RailSection
            title="Not derivable here"
            note="A domain graph needs artifacts no view carries. Named so the gap is visible, not filled."
          >
            <ul className="loom-needs">
              <li><b>Clock tree (sources → PLL → dividers → domains)</b> — needs a clock-structure artifact</li>
              <li><b>Frequencies, uncertainty, jitter per domain</b> — needs a timing-constraint artifact; the draft carries one <code>physical.clock_freq_mhz</code> for the whole design</li>
              <li><b>Synchronizer recommendation and depth</b> — needs the crossing's frequency ratio plus a synchronizer cell library</li>
              <li><b>Power states, isolation, retention, level shifters</b> — needs a power-intent (UPF) artifact</li>
              <li><b>Reset tree and power-up sequence</b> — needs a reset-intent artifact</li>
              <li><b>SDC / UPF export</b> — follows from the two above</li>
            </ul>
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Clock domains', v: String(clockRows.length), tone: 'info' },
            { k: 'Power domains', v: String(powerRows.length), tone: 'info' },
            { k: 'Declared', v: String(declared.length) },
            {
              k: 'Crossings',
              v: String(crossings.length),
              tone: crossings.length ? 'warn' : undefined,
            },
            { k: 'Distinct boundaries', v: String(crossingPairs.length) },
          ]} />

          {rows.length === 0 ? (
            <ExtensionPoint
              title="No agents to assign"
              needs="an agents block on the draft; domains are a property of agents"
            />
          ) : view === 'domains' ? (
            <>
              <RailSection title="Clock domains">
                {table(CLOCK, clockRows)}
              </RailSection>
              <RailSection title="Power domains">
                {table(POWER, powerRows)}
              </RailSection>
              <p className="loom-hint">
                A row counts agents, not groups: an authored group of 64 compute
                tiles contributes 64 agents. <b>Seated</b> is the subset the
                compiler placed on a router, so the two numbers diverge when a
                declared agent has no certified seat.
              </p>
            </>
          ) : (
            <>
              <RailSection
                title="Derived clock-domain crossings"
                note="A channel whose two routers hold agents in different clock domains. Derived from the certified attachment and the authored clock_domain field — not a synchronizer list."
              >
                {crossings.length === 0 ? (
                  <ExtensionPoint
                    title="No crossings to derive"
                    needs={declared.length
                      ? 'agent clock_domain assignments that differ across an adjacency; every agent on this revision is in one domain, or none is declared'
                      : 'a clock_domain on at least one agent group. Without an assignment there is exactly one domain and therefore no boundary to cross.'}
                  />
                ) : (
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th className="num">channel</th>
                        <th>boundary</th>
                        <th className="num">width</th>
                        <th className="num">latency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {crossings.map((c) => (
                        <tr
                          key={c.channelId}
                          className={heldChannel?.channelId === c.channelId ? 'sel' : undefined}
                          onClick={() => sel.select(channelId(c.channelId))}
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              sel.select(channelId(c.channelId));
                            }
                          }}
                        >
                          <td className="num"><code>{c.channelId}</code></td>
                          <td>
                            <code>{c.srcDomain}</code> → <code>{c.dstDomain}</code>
                          </td>
                          <td className="num">{c.widthBits}b</td>
                          <td className="num">{c.latencyCycles} cyc</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </RailSection>
              {crossings.length > 0 && (
                <p className="loom-hint">
                  A channel that touches an undeclared domain appears with{' '}
                  <code>undeclared</code> on one side. That records the absence
                  of an assignment, not a synchronizer requirement — the
                  frequency ratio needed to choose one does not exist yet.
                </p>
              )}
            </>
          )}
        </div>
      }
      right={
        <>
          <RailSection title="Domain inspector">
            {pick ? (
              <>
                <Kv label="kind" value={pick.kind} />
                <Kv label="domain" value={pick.id === 'undeclared'
                  ? <span className="muted">undeclared</span>
                  : <code>{pick.id}</code>} />
                <Kv label="agents" value={String(pick.agentCount)} mono />
                <Kv label="seated agents" value={String(pick.attachedCount)} mono />
                <Kv label="routers" value={String(pick.routers.length)} mono />
                {pick.routers.length > 0 && (
                  <p className="loom-note">
                    Routers {pick.routers.slice(0, 24).map((r) => `R${r}`).join(', ')}
                    {pick.routers.length > 24 && ` … +${pick.routers.length - 24} more`}
                  </p>
                )}
                <p className="loom-note">
                  {pick.id === 'undeclared'
                    ? 'No agent in this group names a domain, so Studio cannot tell a single-domain fabric from an unassigned one.'
                    : 'Named by the authored agent record. The domain carries no frequency, no members list and no source — none of those exist in the contract.'}
                </p>
              </>
            ) : heldCrossing ? (
              <>
                <Kv label="channel" value={<code>{heldCrossing.channelId}</code>} />
                <Kv
                  label="boundary"
                  value={<code>{crossingKey(heldCrossing)}</code>}
                />
                <Kv label="routers" value={
                  <span><code>R{heldCrossing.srcRouter} → R{heldCrossing.dstRouter}</code></span>
                } mono />
                <Kv label="width" value={`${heldCrossing.widthBits} bits`} mono />
                <Kv label="latency" value={`${heldCrossing.latencyCycles} cycles`} mono />
                <p className="loom-note">
                  Selecting a crossing selects the channel that crosses. The
                  boundary is derived from the attachment and the authored
                  assignment, so it is not an object any artifact holds.
                </p>
                <Kv label="same boundary" value={`${pickCrossings.length} channel(s)`} mono />
                <table className="tbl">
                  <thead>
                    <tr><th className="num">channel</th><th>hops</th></tr>
                  </thead>
                  <tbody>
                    {pickCrossings.slice(0, 24).map((c) => (
                      <tr key={c.channelId}>
                        <td className="num"><code>{c.channelId}</code></td>
                        <td><code>R{c.srcRouter} → R{c.dstRouter}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {pickCrossings.length > 24 && (
                  <p className="loom-note">+{pickCrossings.length - 24} more channels</p>
                )}
              </>
            ) : (
              <p className="muted">Select a domain, or a channel in the crossing list.</p>
            )}
          </RailSection>

          <RailSection
            title="Where these numbers come from"
            note="Stated so the census is not mistaken for a power or timing analysis."
          >
            <Kv label="domain names" value="authored (draft.agents[].clock_domain)" />
            <Kv label="agent membership" value="authored group expansion" />
            <Kv label="seating / routers" value={topology ? 'certified attachment' : 'no attachment'} />
            <Kv label="crossings" value="derived (attachment × assignment)" />
            <Kv label="frequencies" value={<span className="status status-muted">NO ARTIFACT</span>} />
            <Kv label="power states" value={<span className="status status-muted">NO ARTIFACT</span>} />
            <Link className="link" to={`/projects/${data.projectId}/loom/agents`}>
              Domain assignment is authored on the draft →
            </Link>
          </RailSection>

          {problems}
        </>
      }
    />
  );
}

function crossingKey(c: Crossing): string {
  return `${c.srcDomain} → ${c.dstDomain}`;
}