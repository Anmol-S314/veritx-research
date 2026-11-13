import type { DeclaredAgent, LoadedProject } from './project';
import type { Topology } from './gateway';
import { parseAddressBigInt } from './agentMap';
import type { IntentSaveState } from './intent';

export type Sel = { kind: 'fabric' } | { kind: 'router'; id: number } | { kind: 'endpoint'; id: number } | { kind: 'range'; id: string };
export type Severity = 'error' | 'warning' | 'unevaluated' | 'info';
export type Problem = { severity: Severity; source: string; code: string; message: string; at?: Sel };
export type Ep = Topology['endpoints'][number];
export type DecodeRow = { name?: string; base?: number | string; size?: number; target_endpoint_id?: number; target_agent_kind?: string };
export type Range = { name?: string; base?: string | number; size?: number; size_bytes?: number; target_agent_idx?: number; target?: number };

export const SEVERITY_ORDER: Severity[] = ['error', 'warning', 'unevaluated', 'info'];
export const SEVERITY_LABEL: Record<Severity, string> = { error: 'Error', warning: 'Warning', unevaluated: 'Not evaluated', info: 'Info' };

export const same = (a: Sel, b: Sel) => a.kind === b.kind && (a as { id?: unknown }).id === (b as { id?: unknown }).id;
export const rangeName = (r: Range, i: number) => r.name || `Range ${i}`;
export const hex = (value: bigint) => `0x${value.toString(16).toUpperCase()}`;

export function rangeBounds(r: Range): { base: bigint; end: bigint } | null {
  const base = parseAddressBigInt(String(r.base ?? ''));
  const size = r.size_bytes ?? r.size;
  if (base === null || typeof size !== 'number' || size <= 0) return null;
  return { base, end: base + BigInt(size) };
}

/** One list from every source the backend already produces: compile verdicts,
 *  certificate obligations, local interval arithmetic and the editor's own save state. */
export function collectProblems(data: LoadedProject, save: IntentSaveState | null): Problem[] {
  const out: Problem[] = [];
  const active = data.detail.active_revision_id;
  if (save?.error) out.push({ severity: 'error', source: 'Save', code: 'SAVE', message: save.error });
  if (save?.dirty) out.push({ severity: 'info', source: 'Compile', code: 'STALE', message: `Edits are unsaved. The verdicts below describe revision ${active ?? 'none'}, not this draft.` });
  if (data.compileResultError) out.push({ severity: 'error', source: 'Compile', code: 'COMPILE', message: data.compileResultError });
  const result = data.compileResult;
  for (const v of result?.stage1_verdicts ?? []) {
    if (v.ok) continue;
    out.push({ severity: 'error', source: `Stage 1 · ${v.module}`, code: v.status, message: [v.reason, ...(v.findings ?? [])].filter(Boolean).join(' — ') || 'Refused without a recorded reason.' });
  }
  for (const finding of result?.stage1_findings ?? []) out.push({ severity: 'warning', source: 'Stage 1', code: 'FINDING', message: finding });
  for (const o of result?.certificate?.obligations ?? []) {
    const status = String(o.status ?? '');
    if (/^(pass|proved|ok|satisfied)/i.test(status)) continue;
    const bad = /fail|violat|refus/i.test(status);
    out.push({ severity: bad ? 'error' : 'unevaluated', source: 'Certificate', code: status || 'UNKNOWN', message: `${o.obligation ?? 'Obligation'}${o.meaning ? ` — ${o.meaning}` : ''}` });
  }
  const ranges = (data.request?.address_map?.ranges ?? []) as Range[];
  const bounds = ranges.map((r, i) => ({ name: rangeName(r, i), b: rangeBounds(r) }));
  for (let i = 0; i < bounds.length; i++) for (let j = i + 1; j < bounds.length; j++) {
    const a = bounds[i].b, b = bounds[j].b;
    if (a && b && a.base < b.end && b.base < a.end) {
      out.push({ severity: 'error', source: 'Local check', code: 'LOCAL-ADDR-01', message: `${bounds[i].name} and ${bounds[j].name} overlap at ${hex(a.base > b.base ? a.base : b.base)}.`, at: { kind: 'range', id: bounds[j].name } });
    }
  }
  return out.sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity));
}

/** Everything the lens shows is joined from served data: topology endpoints, the draft's agent groups and
 *  the compiler's address-decode rows. Nothing here is guessed; a missing join renders as absent. */
export function derive(data: LoadedProject) {
  const eps = data.topology?.endpoints ?? [];
  const agents = (data.request?.agents ?? []) as DeclaredAgent[];
  const rows = ((data.compileResult?.groups?.address_decode as { rows?: DecodeRow[] } | undefined)?.rows ?? []);
  const byRouter = new Map<number, Ep[]>();
  for (const e of eps) byRouter.set(e.router_id, [...(byRouter.get(e.router_id) ?? []), e]);
  const rangesByEp = new Map<number, DecodeRow[]>();
  for (const r of rows) if (typeof r.target_endpoint_id === 'number') rangesByEp.set(r.target_endpoint_id, [...(rangesByEp.get(r.target_endpoint_id) ?? []), r]);
  const kinds = [...new Set(eps.map(e => e.kind))];
  const clocks = [...new Set(agents.map(a => a.clock_domain).filter((c): c is string => !!c))];
  const agentOf = (e: Ep) => agents[e.group_index ?? -1] as DeclaredAgent | undefined;
  const rowFor = (name: string) => rows.find(r => r.name === name);
  return { eps, agents, rows, byRouter, rangesByEp, kinds, clocks, agentOf, rowFor };
}
export type Derived = ReturnType<typeof derive>;
