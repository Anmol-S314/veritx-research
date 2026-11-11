import { useSyncExternalStore } from 'react';

// A semantic context selection, deliberately not a DOM dump. Surfaces mark
// objects with data-context-kind/id/label; the picker resolves the nearest
// marked object, falling back to the visible section or element. The assistant
// receives identity plus the live data it can resolve, never arbitrary HTML.
export type ContextPick = {
  kind: string;
  id: string;
  label: string;
  detail?: string;
};

export type AssistantContextState = {
  open: boolean;
  picking: boolean;
  picks: ContextPick[];
};

let state: AssistantContextState = { open: false, picking: false, picks: [] };
const listeners = new Set<() => void>();
// Fallback picks do not carry data attributes in the page, so remember the
// element they came from. This powers chip hover/scroll without mutating DOM.
const rememberedTargets = new Map<string, Element>();

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
const snapshot = () => state;
const setState = (next: AssistantContextState) => {
  state = next;
  for (const listener of [...listeners]) listener();
};

export const useAssistantContext = (): AssistantContextState =>
  useSyncExternalStore(subscribe, snapshot, snapshot);

export const isAssistantOpen = () => state.open;
export const isPickingContext = () => state.picking;

export function openAssistant(): void {
  setState({ ...state, open: true, picking: false });
}

export function closeAssistant(): void {
  setState({ ...state, open: false });
}

export function toggleAssistant(): void {
  setState({ ...state, open: !state.open, picking: false });
}

export function startPicking(): void {
  setState({ ...state, open: true, picking: true });
}

export function stopPicking(): void {
  setState({ ...state, picking: false });
}

export function attachPick(pick: ContextPick, options: { keepPicking?: boolean } = {}): void {
  const existing = state.picks.find(item => item.kind === pick.kind && item.id === pick.id);
  const picks = existing
    ? state.picks.map(item => item.kind === pick.kind && item.id === pick.id ? pick : item)
    : [...state.picks, pick].slice(-8);
  setState({ ...state, open: true, picking: Boolean(options.keepPicking), picks });
}

export function removePick(kind: string, id: string): void {
  setState({ ...state, picks: state.picks.filter(item => !(item.kind === kind && item.id === id)) });
}

export function clearPicks(): void {
  if (!state.picks.length) return;
  rememberedTargets.clear();
  setState({ ...state, picks: [] });
}

/** React props for a semantic context target. Kept tiny so dense tables and
 *  SVG nodes can carry a target without a wrapper element. */
export function contextTarget(kind: string, id: string | number, label: string, detail?: string): Record<string, string> {
  const props: Record<string, string> = {
    'data-context-kind': kind,
    'data-context-id': String(id),
    'data-context-label': label,
  };
  if (detail) props['data-context-detail'] = detail.slice(0, 600);
  return props;
}

const textOf = (element: Element | null, limit = 220): string => {
  const text = (element?.getAttribute('aria-label') || element?.textContent || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
};

const headingOf = (element: Element): string => {
  const owner = element.closest('section, article, figure, .card, .stat, tr, li, aside');
  const heading = owner?.querySelector('h2, h3, h4, th, legend') ?? element.closest('section, article')?.querySelector('h2, h3');
  const value = textOf(heading ?? null, 90);
  if (value) return value;
  const pageHeading = document.querySelector('.page-heading h1');
  return textOf(pageHeading, 90) || 'Selected region';
};

/** A compact identity for a leaf object. Table cells combine the row label,
 *  the column label and the cell value; stat cards combine their label and
 *  value. This is what makes a picked row or KPI feel like an object rather
 *  than "somewhere inside the section". */
const objectLabel = (element: Element): string => {
  const tag = element.tagName.toLowerCase();
  const unique = (values: string[]) => {
    const seen = new Set<string>();
    return values.filter(value => {
      const key = value.toLowerCase();
      if (!value || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };
  if (element.matches('.stat, .router-kpis > div, .delay-row, .bar-row, .flow-row, .router-hotspot, .load-bin-readout')) {
    const primary = textOf(element.querySelector('span, .mono, strong, th, h3'), 90);
    const value = textOf(element.querySelector('strong, b, .numeric, .delay-row-value'), 90);
    const combined = unique([primary, value]).join(' · ');
    if (combined) return combined;
  }
  if (tag === 'tr') {
    const cells = Array.from(element.children).filter(cell => /^(TD|TH)$/.test(cell.tagName)).slice(0, 3).map(cell => textOf(cell, 90));
    const combined = unique(cells).join(' · ');
    if (combined) return combined;
  }
  if (tag === 'td' || tag === 'th') {
    const row = element.closest('tr');
    const rowLabel = textOf(row?.querySelector('th, td') ?? null, 90);
    const table = element.closest('table');
    const cellIndex = (element as HTMLTableCellElement).cellIndex;
    const columnLabel = cellIndex >= 0 ? textOf(table?.querySelector('thead tr')?.children[cellIndex] ?? null, 90) : '';
    const combined = unique([rowLabel, columnLabel, textOf(element, 90)]).join(' · ');
    if (combined) return combined;
  }
  if (tag === 'figure') {
    const title = textOf(element.querySelector('h3, h2, figcaption'), 110);
    if (title) return title;
  }
  if (/^(button|a|label|summary|p|li)$/.test(tag)) {
    const name = textOf(element, 100);
    if (name) return name;
  }
  return headingOf(element);
};

/** Readable HTML text only. SVG text is deliberately excluded: adjacent chart
 *  labels have no separators in textContent and become an unreadable blob such
 *  as "R03,216R13,216". Block-level lines are de-duplicated and bounded. */
const readableExcerpt = (element: Element, limit = 420): string => {
  const blocks = Array.from(element.querySelectorAll('h2, h3, h4, p, li, dt, dd, td, th, .meta-line, .stat, figcaption, summary'))
    .filter(block => !block.closest('svg'))
    .map(block => textOf(block, 180))
    .filter(Boolean);
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const block of blocks) {
    const key = block.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    lines.push(block);
    if (lines.join(' · ').length >= limit) break;
  }
  const joined = lines.join(' · ');
  return joined.length > limit ? `${joined.slice(0, limit - 1)}…` : joined;
};

const hashText = (value: string): string => {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
};

const pageLabel = (): string => {
  const heading = document.querySelector('.page-heading h1');
  return textOf(heading, 90) || 'Current view';
};

const routeLabel = (): string => {
  const hash = window.location.hash.replace(/^#\/?/, '');
  return hash || 'design/system';
};

export type ContextSelection = { pick: ContextPick; element: Element };

// What "one level finer than a section" means. Section headings are omitted on
// purpose: clicking a section heading should still pick the section, while a
// row, card, cell, chart or button inside it should pick that leaf object.
const FINE_TARGETS = 'figure, .card, .stat, .router-kpis > div, .delay-row, .bar-row, .flow-row, .router-hotspot, .load-bin-readout, tr, li, p, td, th, h1, button, a, label, summary, [role="button"]';

function markedSelection(element: Element): ContextSelection {
  const kind = element.getAttribute('data-context-kind') || 'element';
  const label = element.getAttribute('data-context-label') || textOf(element) || `${kind} selection`;
  const id = element.getAttribute('data-context-id') || `${kind}:${hashText(label)}`;
  const detail = element.getAttribute('data-context-detail') || undefined;
  return { pick: { kind, id, label, detail }, element };
}

function leafSelection(container: Element): ContextSelection {
  const tag = container.tagName.toLowerCase();
  const label = objectLabel(container);
  const excerpt = tag === 'svg' ? '' : readableExcerpt(container);
  const kind = /^(section|article|aside)$/.test(tag) ? 'section'
    : container.matches('.stat, .router-kpis > div, .load-bin-readout') ? 'metric'
    : tag === 'figure' ? 'chart'
    : tag === 'tr' ? 'row'
    : tag === 'td' || tag === 'th' ? 'cell'
    : 'element';
  const detail = [`route: ${routeLabel()}`, `element: <${tag}>`, excerpt ? `readable text: ${excerpt}` : ''].filter(Boolean).join('\n');
  return {
    pick: {
      kind,
      id: `${kind}:${hashText(`${label}|${excerpt}|${tag}`)}`,
      label: kind === 'section' && label === pageLabel() ? `${label} · region` : label,
      detail,
    },
    element: container,
  };
}

/** Resolve what a click should attach. A semantic target wins when it is a
 *  row, node, channel, or other domain object. When the nearest marked target
 *  is only a section, a finer card/row/cell/chart under the pointer wins. */
export function resolveContextSelection(start: Element | null): ContextSelection | null {
  if (!start || !(start instanceof Element)) return null;
  if (start.closest('[data-context-ignore]')) return null;
  if (start === document.documentElement || start === document.body) return null;
  const marked = start.closest('[data-context-kind]');
  const fine = start.closest(FINE_TARGETS);
  const markedKind = marked?.getAttribute('data-context-kind');
  const sectionIsOnlyContainer = Boolean(marked && fine && marked !== fine && markedKind === 'section' && marked.contains(fine));
  const remember = (selection: ContextSelection | null) => {
    if (selection) rememberedTargets.set(`${selection.pick.kind}:${selection.pick.id}`, selection.element);
    return selection;
  };
  if (marked && !sectionIsOnlyContainer) return remember(markedSelection(marked));
  if (fine) return remember(leafSelection(fine));
  if (marked) return remember(markedSelection(marked));
  return null;
}

export function resolveContextTarget(start: Element | null): ContextPick | null {
  return resolveContextSelection(start)?.pick ?? null;
}

/** Find the live target for a chip so hover can reveal where it came from. */
export function findContextTarget(kind: string, id: string): Element | null {
  const key = `${kind}:${id}`;
  const remembered = rememberedTargets.get(key);
  if (remembered?.isConnected) return remembered;
  if (remembered) rememberedTargets.delete(key);
  const selector = `[data-context-kind="${CSS.escape(kind)}"][data-context-id="${CSS.escape(id)}"]`;
  return document.querySelector(selector);
}

export function describePick(pick: ContextPick): string {
  return pick.detail ? `${pick.label} · ${pick.detail.split('\n')[0]}` : pick.label;
}

/** Briefly outline the element a context chip came from. */
export function flashContextTarget(kind: string, id: string): Element | null {
  const element = findContextTarget(kind, id);
  if (!element) return null;
  element.classList.remove('context-target-flash');
  void (element as HTMLElement).offsetWidth;
  element.classList.add('context-target-flash');
  window.setTimeout(() => element.classList.remove('context-target-flash'), 1400);
  return element;
}
