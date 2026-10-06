import type { ReactElement, ReactNode } from 'react';

/** Three-pane Loom frame: left rail (context + parameters), stage (the view
 *  itself), right rail (selection inspector). Views compose their own panes so
 *  each one can decide which rails it actually has content for. */
export function Panes({ left, stage, right }: {
  left?: ReactNode;
  stage: ReactNode;
  right?: ReactNode;
}): ReactElement {
  return (
    <div className={`loom-panes${left ? '' : ' no-left'}${right ? '' : ' no-right'}`}>
      {left && <aside className="loom-rail loom-rail-left">{left}</aside>}
      <section className="loom-stage">{stage}</section>
      {right && <aside className="loom-rail loom-rail-right">{right}</aside>}
    </div>
  );
}

export function RailSection({ title, note, children }: {
  title: string;
  note?: ReactNode;
  children: ReactNode;
}): ReactElement {
  return (
    <section className="loom-section">
      <h3 className="loom-section-title">{title}</h3>
      {children}
      {note && <p className="loom-note">{note}</p>}
    </section>
  );
}

/** The Loom convention for a panel the frozen contract cannot back: keep the
 *  panel in place, name the artifact it needs, draw no approximation. */
export function ExtensionPoint({ title, needs, children }: {
  title: string;
  needs: string;
  children?: ReactNode;
}): ReactElement {
  return (
    <div className="loom-ext" role="note">
      <div className="loom-ext-title">{title}</div>
      <p className="loom-ext-body">
        Requires {needs.replace(/[.]+$/, '')}. Nothing is estimated or drawn
        until that artifact exists.
      </p>
      {children}
    </div>
  );
}

export type StripTone = 'ok' | 'bad' | 'warn' | 'info';

export function SummaryStrip({ items }: {
  items: { k: string; v: ReactNode; tone?: StripTone }[];
}): ReactElement {
  return (
    <div className="loom-strip">
      {items.map((item) => (
        <div className="loom-strip-cell" key={item.k}>
          <span className="loom-strip-key">{item.k}</span>
          <span className={`loom-strip-val${item.tone ? ` t-${item.tone}` : ''}`}>
            {item.v}
          </span>
        </div>
      ))}
    </div>
  );
}

/** A plane / mode card in the left rail. Colors are semantic roles, not
 *  decoration: each plane keeps one identity across every view. */
export function PlaneCard({ id, label, detail, active, onSelect, available = true }: {
  id: string;
  label: string;
  detail: string;
  active: boolean;
  onSelect: () => void;
  available?: boolean;
}): ReactElement {
  return (
    <button
      type="button"
      className={`loom-plane plane-${id}${active ? ' active' : ''}`}
      aria-pressed={active}
      onClick={onSelect}
    >
      <span className="loom-plane-dot" aria-hidden="true" />
      <span className="loom-plane-text">
        <b>{label}</b>
        <em>{detail}</em>
      </span>
      {!available && <span className="loom-plane-flag">no artifact</span>}
    </button>
  );
}

export function Kv({ label, value, mono = false }: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}): ReactElement {
  return (
    <div className="kv">
      <span>{label}</span>
      <span className={mono ? 'num' : undefined}>{value}</span>
    </div>
  );
}

export function Stat({ value, unit, label, tone }: {
  value: ReactNode;
  unit?: string;
  label: string;
  tone?: StripTone;
}): ReactElement {
  return (
    <div className="loom-stat">
      <div className={`loom-stat-value${tone ? ` t-${tone}` : ''}`}>
        {value}
        {unit && <span className="loom-stat-unit">{unit}</span>}
      </div>
      <div className="loom-stat-label">{label}</div>
    </div>
  );
}
