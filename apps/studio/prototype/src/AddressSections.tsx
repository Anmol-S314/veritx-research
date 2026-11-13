import type { ReactNode } from 'react';
import { addressCoverage, formatBytes, formatHex, validateWindows, type AddressWindow, type AgentGroup } from './agentMap';
import { Badge, Empty, Notice, Properties, Section } from './ui';
import { LiveAddressMap } from './LiveAddressMap';

/** One address surface: the windowed map, the declared windows table, and the
 *  coverage/blocking summary. Resolved decode rows are optional, because they
 *  exist only after a compile. */
export type ResolvedWindow = {
  base?: bigint | number | string;
  size?: bigint | number | string;
  target_endpoint_id?: number | null;
  target_agent_kind?: string | null;
};

export function AddressSections({ windows, agents, selected, onSelect, resolvedRows = [], resolvedColumns = false, endpointById, targetLabelById, coverageExtra = [], banner, footer }: {
  windows: AddressWindow[];
  agents: AgentGroup[];
  selected: string | null;
  onSelect: (id: string) => void;
  resolvedRows?: ResolvedWindow[];
  resolvedColumns?: boolean;
  endpointById?: Map<number, { endpoint_id: number; router_id: number; port_id: number }>;
  /** Declared target text when it names an integration boundary rather than a compiled agent. */
  targetLabelById?: Map<string, string>;
  coverageExtra?: [string, ReactNode][];
  banner?: ReactNode;
  footer?: ReactNode;
}) {
  const coverage = addressCoverage(windows);
  const issues = validateWindows(windows, agents);
  const blocking = issues.filter(issue => issue.severity === 'error');
  const rowFor = (window: AddressWindow) => resolvedRows.find(row => sameQuantum(row.base, window.base) && sameQuantum(row.size, window.size));

  return <>
    {banner}
    {!windows.length ? <Empty title="No declared address windows">
      This document declares no address ranges. An empty map resolves to an empty decode table; targets have no system address.
    </Empty> : <>
      <Section title="Address-space map" actions={<Badge>{windows.length} window{windows.length === 1 ? '' : 's'}</Badge>}>
        <LiveAddressMap windows={windows} agents={agents} selected={selected} onSelect={onSelect} />
      </Section>
      <Section title="Declared address windows" actions={<Badge>{windows.length} window{windows.length === 1 ? '' : 's'}</Badge>}>
        <div className="table-scroll"><table><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target</th><th>Selection</th>{resolvedColumns && <><th>Resolved base / size</th><th>Target router / port</th><th>Resolved endpoint</th></>}</tr></thead><tbody>
          {windows.map(window => {
            const row = rowFor(window);
            return <tr key={window.id} className={window.id === selected ? 'selected' : ''}><th><button className="text-button mono" onClick={() => onSelect(window.id)}>{window.name || 'unnamed'}</button></th><td className="mono">{formatHex(window.base)}</td><td>{formatBytes(window.size)}</td><td>{targetLabelById?.get(window.id) ?? agents[window.targetAgentIdx]?.kind ?? `agent ${window.targetAgentIdx}`}</td><td>{window.selectionPolicy ?? 'group'}{window.selectionPolicy === 'FIXED_INSTANCE' ? ` · ${window.targetInstanceIndex ?? 0}` : window.selectionPolicy === 'STRIPED' ? ` · ${formatBytes(window.interleaveBytes ?? 0n)}` : ''}</td>{resolvedColumns && <>
              <td className="mono">{row?.base !== undefined && row?.size !== undefined ? `${formatHex(row.base)} · ${formatBytes(row.size)}` : 'Not recorded'}</td>
              <td className="mono">{(() => { const seat = row?.target_endpoint_id !== undefined && row?.target_endpoint_id !== null ? endpointById?.get(row.target_endpoint_id) : undefined; return seat ? `R${seat.router_id} / p${seat.port_id}` : row?.target_endpoint_id !== undefined && row?.target_endpoint_id !== null ? `endpoint ${row.target_endpoint_id}` : 'Not recorded'; })()}</td>
              <td>{row ? `${row.target_agent_kind ?? 'target'} · endpoint ${row.target_endpoint_id ?? '—'}` : 'not in active revision'}</td>
            </>}</tr>;
          })}
        </tbody></table></div>
      </Section>
      <Section title="Coverage and blocking checks" actions={<Badge tone={blocking.length ? 'red' : 'green'}>{blocking.length ? `${blocking.length} open` : 'None'}</Badge>}>
        <Properties rows={[
          ['Declared bytes', formatBytes(coverage.declaredBytes)],
          ['Mapped union', formatBytes(coverage.mappedBytes)],
          ['Overlapping bytes', formatBytes(coverage.overlapBytes)],
          ['Highest end', <code>{formatHex(coverage.maxEnd)}</code>],
          ...coverageExtra,
        ]} />
        {issues.length > 0 && <div className="table-scroll"><table><thead><tr><th>Severity</th><th>Code</th><th>Windows</th><th>Detail</th></tr></thead><tbody>
          {groupIssues(issues).map(group => <tr key={group.key}><td><Badge tone={group.severity === 'error' ? 'red' : 'amber'}>{group.severity}</Badge></td><td className="mono">{group.code}</td><td>{group.windows.join(', ')}</td><td>{group.detail}</td></tr>)}
        </tbody></table></div>}
        {issues.length === 0 && <Notice tone="blue">Every declared window is inside the 48-bit space and none overlaps another. Decode and permission enforcement are still not evaluated.</Notice>}
      </Section>
      {footer}
    </>}
  </>;
}

/** One row per distinct (severity, code, detail); repeated windows list once. */
function groupIssues(issues: { window: string; severity: 'error' | 'warning'; code: string; detail: string }[]) {
  const groups = new Map<string, { key: string; severity: 'error' | 'warning'; code: string; detail: string; windows: string[] }>();
  for (const issue of issues) {
    const key = `${issue.severity}|${issue.code}|${issue.detail}`;
    const group = groups.get(key) ?? { key, severity: issue.severity, code: issue.code, detail: issue.detail, windows: [] };
    if (!group.windows.includes(issue.window)) group.windows.push(issue.window);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function sameQuantum(value: unknown, expected: bigint) {
  if (value === undefined || value === null) return false;
  try { return BigInt(value as bigint) === expected; } catch { return false; }
}
