import { useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import type { PageId, PrototypeState } from './model';

export type ViewProps = { state: PrototypeState; setState: Dispatch<SetStateAction<PrototypeState>>; notify: (message: string) => void; navigate: (page: PageId) => void };
const paths: Record<string, string> = {
  assistant: 'M4 4h16v12H9l-5 5V4z M8 8h8 M8 12h5',
  target: 'M12 3v3 M12 18v3 M3 12h3 M18 12h3 M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z',
  network: 'M4 5h5v5H4z M15 14h5v5h-5z M4 14h5v5H4z M6.5 10v4 M9 7.5h8.5V14',
  cube: 'm12 3 9 5-9 5-9-5 9-5z M3 8v9l9 5 9-5V8 M12 13v9',
  search: 'M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15z m5.5-2 5 5',
  settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
  table: 'M3 4h18v16H3z M3 9h18 M9 4v16 M3 14h18',
  arrow: 'M4 12h16 m-6-6 6 6-6 6',
  plus: 'M12 5v14 M5 12h14',
  close: 'm6 6 12 12 M18 6 6 18',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l4 2',
  compare: 'M8 3v18 M16 3v18 M3 8h10 M11 16h10',
  layers: 'm12 3 10 5-10 5L2 8l10-5z M2 12l10 5 10-5 M2 16l10 5 10-5',
  chart: 'M4 3v17h17 M7 15l5-5 4 2 5-7',
  check: 'm5 12 4 4 10-10',
  warning: 'm12 3 10 18H2L12 3z M12 9v5 M12 17v1',
  file: 'M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 17h6',
  download: 'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',
  branch: 'M6 3v14a3 3 0 1 0 3-3H6 M6 8h8a4 4 0 0 0 4-4V3',
  shield: 'M12 3 3 7v6c0 4 9 9 9 9s9-5 9-9V7l-9-4z m-5 9 4 4 6-7',
  folder: 'M3 6h7l2 3h9v12H3V6z',
  terminal: 'm4 6 6 6-6 6 M13 18h7',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 10v7 M12 6v1',
};
export function Icon({ name = 'file', size = 16 }: { name?: string; size?: number }) { return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name] ?? paths.file} /></svg>; }
export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: 'neutral' | 'blue' | 'green' | 'amber' | 'red'; title?: string }) { return <span className={`badge ${tone}`} title={title}>{children}</span>; }
export function Outcome({ value }: { value: string }) { const tone = /Violated|Failed|Invalid|Conflict/.test(value) ? 'red' : /Not evaluated|Partial|Unknown|Inconclusive|Not established/.test(value) ? 'amber' : /Met|Pass|Complete/.test(value) ? 'green' : 'neutral'; return <Badge tone={tone}>{value}</Badge>; }
export function Button({ children, onClick, primary = false, disabled = false, title, type = 'button', danger = false, className = '' }: { children: ReactNode; onClick?: () => void; primary?: boolean; disabled?: boolean; title?: string; type?: 'button' | 'submit'; danger?: boolean; className?: string }) { return <button type={type} className={`button ${primary ? 'primary' : ''} ${danger ? 'danger' : ''}${className ? ` ${className}` : ''}`} onClick={onClick} disabled={disabled} title={title}>{children}</button>; }
export function PageLink({ page, children, primary = false }: { page: PageId; children: ReactNode; primary?: boolean }) { return <a className={`button ${primary ? 'primary' : ''}`} href={`#/${page}`}>{children}</a>; }
export function Section({ title, children, actions, id }: { title: string; children: ReactNode; actions?: ReactNode; id?: string }) { return <section className="section" id={id} data-context-kind="section" data-context-id={id ?? `section:${title}`} data-context-label={title}><div className="section-heading"><h2>{title}</h2>{actions && <div className="actions">{actions}</div>}</div>{children}</section>; }
/** Scope, provenance and method notes stay at the call sites for reference but
 *  are intentionally not rendered in this prototype build. */
export function Assumptions(_props: { rows?: [string, ReactNode][]; children?: ReactNode; title?: string }) {
  return null;
}
export const Caveats = Assumptions;
export function Notice({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'amber' | 'red' | 'blue' }) { return <div className={`notice ${tone}`}><Icon name={tone === 'red' || tone === 'amber' ? 'warning' : 'info'} /><div>{children}</div></div>; }
/** One sticky action bar for every draft surface: status and errors on the left,
 *  the primary action on the right. Callers pass only the state they must show. */
export function ActionBar({ status, children, className = '', sticky = true }: { status?: ReactNode; children: ReactNode; className?: string; sticky?: boolean }) {
  return <div className={`action-bar${sticky ? '' : ' action-bar-static'}${className ? ` ${className}` : ''}`}>
    <div className="action-bar-status">{status}</div>
    <div className="actions">{children}</div>
  </div>;
}
export function Properties({ rows }: { rows: [string, ReactNode][] }) { return <dl className="properties">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>; }
export function Inspector({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <><button className="button inspector-toggle" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="selection-inspector"><Icon name="settings" />Inspector</button><aside id="selection-inspector" className="inspector" data-open={open}><div className="inspector-heading"><h2>{title}</h2><button className="icon-button inspector-close" aria-label="Close inspector" onClick={() => setOpen(false)}><Icon name="close" /></button></div><div className="inspector-content">{children}</div></aside></>;
}
export function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const d = ref.current!; d.showModal(); return () => { if (d.open) d.close(); }; }, []);
  return <dialog ref={ref} className="dialog" aria-labelledby="dialog-title" onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}><div className="dialog-heading"><h2 id="dialog-title">{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><Icon name="close" /></button></div><div className="dialog-content">{children}</div></dialog>;
}
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) { return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>; }
/** A connection or verdict light. The text beside it always carries the same
 *  state, so colour is never the only signal. */
export function StatusDot({ tone = 'neutral', pulse = false }: { tone?: 'neutral' | 'blue' | 'green' | 'amber' | 'red'; pulse?: boolean }) {
  return <span className={`status-dot ${tone}${pulse ? ' pulse' : ''}`} aria-hidden="true" />;
}
export function Empty({ title, children, icon = 'info', action }: { title: string; children: ReactNode; icon?: string; action?: ReactNode }) {
  return <div className="empty"><span className="empty-icon"><Icon name={icon} size={22} /></span><div className="empty-copy"><h2>{title}</h2><div className="empty-body">{children}</div></div>{action && <div className="empty-action">{action}</div>}</div>;
}
/** A code surface with its own identity bar. Used for evidence documents and
 *  generated JSON so the path, size and copy action stay attached to the data. */
export function CodePanel({ title, actions, children }: { title: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return <div className="code-panel"><div className="code-panel-head"><span className="code-panel-title">{title}</span>{actions && <div className="actions">{actions}</div>}</div><pre className="code-preview">{children}</pre></div>;
}
export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const area = document.createElement('textarea'); area.value = text; area.style.position = 'fixed'; area.style.opacity = '0';
      document.body.appendChild(area); area.select(); document.execCommand('copy'); area.remove();
    }
    setCopied(true); window.setTimeout(() => setCopied(false), 1500);
  };
  return <button type="button" className="button" onClick={copy} aria-live="polite"><Icon name="file" size={13} />{copied ? 'Copied' : label}</button>;
}
const jsonScalarClass = (value: unknown) => typeof value === 'string' ? 'json-string' : typeof value === 'number' ? 'json-number' : typeof value === 'boolean' ? 'json-boolean' : 'json-null';
const jsonScalarText = (value: unknown) => typeof value === 'string' ? JSON.stringify(value) : value === null ? 'null' : String(value);

function JsonNode({ name, value, depth }: { name?: string; value: unknown; depth: number }) {
  if (value !== null && typeof value === 'object') {
    const isArray = Array.isArray(value);
    const entries: [string, unknown][] = isArray
      ? (value as unknown[]).map((item, index) => [String(index), item])
      : Object.entries(value as Record<string, unknown>);
    // A closed branch renders no descendants. With 21 workload cards on the
    // start page this is the difference between ~1.5k and ~15k DOM nodes.
    const [open, setOpen] = useState(depth < 1);
    return <details className="json-branch" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>
        {name !== undefined && <span className="json-key">{name}</span>}
        <span className="json-punct">{isArray ? '[' : '{'}</span>
        <span className="json-count">{entries.length} {isArray ? (entries.length === 1 ? 'item' : 'items') : (entries.length === 1 ? 'key' : 'keys')}</span>
        <span className="json-punct">{isArray ? ']' : '}'}</span>
      </summary>
      {open && entries.length > 0 && <div className="json-children">{entries.map(([key, child]) => <JsonNode key={key} name={key} value={child} depth={depth + 1} />)}</div>}
    </details>;
  }
  return <div className="json-leaf">
    {name !== undefined && <span className="json-key">{name}</span>}
    <span className={`json-value ${jsonScalarClass(value)}`}>{jsonScalarText(value)}</span>
  </div>;
}

/** A definition is read as structure, not as one wall of JSON: top-level keys
 *  stay expanded, long branches fold, and the raw document remains copyable. */
export function JsonView({ value, name = 'JSON', hint }: { value: unknown; name?: string; hint?: ReactNode }) {
  const text = JSON.stringify(value, null, 2) ?? '';
  const root = value !== null && typeof value === 'object';
  const entries: [string, unknown][] = !root ? [['value', value]]
    : Array.isArray(value) ? (value as unknown[]).map((item, index) => [String(index), item])
      : Object.entries(value as Record<string, unknown>);
  return <div className="json-view">
    <div className="json-view-head">
      <span className="json-view-title">{name}</span>
      <span className="json-view-meta">{root ? `${entries.length} top-level ${Array.isArray(value) ? (entries.length === 1 ? 'item' : 'items') : (entries.length === 1 ? 'key' : 'keys')} · ` : ''}{text.length.toLocaleString()} B</span>
      <div className="actions"><CopyButton text={text} label="Copy JSON" /></div>
    </div>
    {hint && <p className="json-view-hint meta-line">{hint}</p>}
    <div className="json-view-body">
      {entries.length ? entries.map(([key, child]) => <JsonNode key={key} name={root ? key : undefined} value={child} depth={0} />) : <span className="muted">No keys</span>}
    </div>
  </div>;
}
export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function formatError(e: unknown) { return e instanceof Error ? e.message : 'This local operation could not be completed.'; }
