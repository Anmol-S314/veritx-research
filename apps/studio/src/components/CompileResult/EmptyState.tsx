import type { ReactElement, ReactNode } from 'react';

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
