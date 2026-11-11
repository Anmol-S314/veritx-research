import { useMemo, useState, type ReactElement } from 'react';
import type { RunSummary } from '../../api/types';
import { filterRunHistory, runFingerprintFreshness } from './runHistory';

/** Search-only view of gateway run summaries; preserves every source record. */
export default function RunHistoryPanel({ runs, currentDesignHash }: {
  runs: RunSummary[];
  currentDesignHash: string | null;
}): ReactElement {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => filterRunHistory(runs, query, currentDesignHash), [runs, query, currentDesignHash]);
  return (
    <div className="loom-run-history">
      <label className="loom-field">
        <span>Search run history</span>
        <input aria-label="Search run history" value={query} onChange={event => setQuery(event.target.value)} placeholder="run, status, backend, workload, fingerprint" />
      </label>
      <p className="muted">{visible.length} of {runs.length} runs · includes non-evaluated outcomes</p>
      <ul>
        {visible.map(item => {
          const freshness = runFingerprintFreshness(item.design_hash, currentDesignHash);
          const freshnessLabel = freshness === 'older'
            ? 'older project fingerprint'
            : freshness === 'current'
              ? 'current project fingerprint'
              : 'fingerprint freshness unknown';
          const short = (v: string | null | undefined): string =>
            v == null || v === '' ? '—' : v.length > 18 ? `${v.slice(0, 18)}…` : v;
          return (
            <li key={item.run_id} title={`workload ${item.workload_id ?? '—'} · fingerprint ${item.design_hash ?? '—'}`}>
              <code>{item.display_name ?? item.run_id}</code> · {item.status ?? 'UNKNOWN'} · <code>{item.backend ?? '—'}</code> · <code>{short(item.workload_id)}</code> · <code>{short(item.design_hash)}</code> · <span aria-label={`Project fingerprint ${freshness}`} className={freshness === 'older' ? 'warn' : 'muted'}>{freshnessLabel}</span>
            </li>
          );
        })}
      </ul>
      {runs.length > 0 && visible.length === 0 && <p className="muted">No run matches this search.</p>}
    </div>
  );
}
