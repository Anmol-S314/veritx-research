import type { ReactElement } from 'react';

/** Decorative SROTA mark (the adjacent text carries the name). */
export default function BrandMark(): ReactElement {
  return (
    <div className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 44 44">
        <path d="M8 11h10v10H8zM26 11h10v10H26zM8 29h10v7H8zM26 29h10v7H26z" />
        <path className="trace" d="M18 16h8M13 21v8M31 21v8M18 32h8" />
      </svg>
    </div>
  );
}
