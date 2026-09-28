import type { ReactElement, ReactNode } from 'react';

/** A meaningful state for zero rows — never a blank table (P0 BUG 3).
 *
 * Rule: ZERO ROWS renders MEANINGFUL STATE, not an empty `<tbody>`.
 * Every table in the Compile Result must either have rows or be replaced
 * by one of these states.
 */
export function EmptyState({ title, children }: {
  title: string;
  children?: ReactNode;
}): ReactElement {
  return (
    <div className="empty-state" role="status">
      <p><strong>{title}</strong></p>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}
