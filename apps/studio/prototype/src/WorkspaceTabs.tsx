import type { PageId } from './model';

/** One horizontal section strip per workspace, directly under the page
 *  heading. Items are real links so deep links, history and open-in-new-tab
 *  keep working. A workspace with a single destination renders no strip. */
export function WorkspaceTabs({ label, current, items }: {
  label: string;
  current?: PageId;
  items: { id: PageId; label: string }[];
}) {
  if (items.length < 2) return null;
  return <nav className="workspace-tabs" aria-label={label}>
    {items.map(item => <a key={item.id} href={`#/${item.id}`}
      aria-current={current === item.id ? 'page' : undefined}>{item.label}</a>)}
  </nav>;
}
