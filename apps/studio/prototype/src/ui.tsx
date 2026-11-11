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
export function Button({ children, onClick, primary = false, disabled = false, title, type = 'button', danger = false }: { children: ReactNode; onClick?: () => void; primary?: boolean; disabled?: boolean; title?: string; type?: 'button' | 'submit'; danger?: boolean }) { return <button type={type} className={`button ${primary ? 'primary' : ''} ${danger ? 'danger' : ''}`} onClick={onClick} disabled={disabled} title={title}>{children}</button>; }
export function PageLink({ page, children, primary = false }: { page: PageId; children: ReactNode; primary?: boolean }) { return <a className={`button ${primary ? 'primary' : ''}`} href={`#/${page}`}>{children}</a>; }
export function Section({ title, children, actions, id }: { title: string; children: ReactNode; actions?: ReactNode; id?: string }) { return <section className="section" id={id} data-context-kind="section" data-context-id={id ?? `section:${title}`} data-context-label={title}><div className="section-heading"><h2>{title}</h2>{actions && <div className="actions">{actions}</div>}</div>{children}</section>; }
/** The single, page-level disclosure every view ends with. Scope, provenance
 *  and method notes live here instead of interleaved with the work. */
export function Assumptions({ rows, children, title = 'Assumptions & scope' }: { rows?: [string, ReactNode][]; children?: ReactNode; title?: string }) {
  return <details className="assumptions" data-context-kind="section" data-context-label={title}>
    <summary>{title}</summary>
    <div className="assumptions-body">{rows && rows.length > 0 && <Properties rows={rows} />}{children}</div>
  </details>;
}
export const Caveats = Assumptions;
export function Notice({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'amber' | 'red' | 'blue' }) { return <div className={`notice ${tone}`}><Icon name={tone === 'red' || tone === 'amber' ? 'warning' : 'info'} /><div>{children}</div></div>; }
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
export function Empty({ title, children }: { title: string; children: ReactNode }) { return <div className="empty"><Icon name="info" size={28} /><h2>{title}</h2><p>{children}</p></div>; }
export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function formatError(e: unknown) { return e instanceof Error ? e.message : 'This local operation could not be completed.'; }
