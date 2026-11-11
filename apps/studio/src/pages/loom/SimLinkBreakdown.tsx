/** Measured per-link wait/Tx split for one run and channel.
 *
 * Queue latency, arb-wait and buffer depth are read from the loom
 * simulation link endpoint (measured window aggregates, never
 * interpolated). A null breakdown renders the named absence, never
 * zeros; a run or channel mismatch withholds the numbers entirely.
 */
import { useEffect, useState, type ReactElement } from 'react';
import type { LoomData } from './data';
import { api, ApiError } from '../../api';
import type { SimLinkView } from '../../api/types';
import { useAsync } from '../../studio';
import { From, Kv, RailSection } from './parts';

function fmt(value: number | null, digits = 2): string {
  return value == null ? '—' : value.toFixed(digits);
}

function BreakdownBar({ view }: { view: SimLinkView }): ReactElement | null {
  const split = view.breakdown;
  if (!split) return null;
  const queue = split.queue_cycles;
  const arb = split.arb_wait_cycles;
  const tx = split.tx_busy_cycles ?? 0;
  const total = queue + arb + tx;
  if (!(total > 0)) return null;
  const width = (part: number): string => `${((part / total) * 100).toFixed(1)}%`;
  return (
    <div aria-label={`Wait over Tx split for channel ${view.logical_channel_id}`}>
      <div className="splitbar" role="img"
        aria-label={`queue ${queue} cycles, arb-wait ${arb} cycles, Tx ${tx} cycles`}>
        <span className="splitbar-queue" style={{ width: width(queue) }} />
        <span className="splitbar-arb" style={{ width: width(arb) }} />
        <span className="splitbar-tx" style={{ width: width(tx) }} />
      </div>
      <ul className="loom-needs">
        <li><b>queue</b> — {queue.toLocaleString()} cycles (head flit present, no credit)</li>
        <li><b>arb-wait</b> — {arb.toLocaleString()} cycles (grantable, ungranted)</li>
        <li><b>Tx</b> — {tx.toLocaleString()} busy cycles over {split.tx_flits.toLocaleString()} grants</li>
      </ul>
    </div>
  );
}

export function SimLinkBreakdown({ data, runId, channelId }: {
  data: LoomData | null;
  runId: string | null;
  channelId: string | number | null;
}): ReactElement {
  const link = useAsync(
    () => (runId != null && channelId != null
      ? api.simLink(runId, channelId)
      : Promise.resolve(null)),
    [runId, channelId],
  );
  const view = link.result.state === 'ready' ? link.result.data : null;
  const identityMatches = Boolean(
    runId != null && channelId != null && view?.run === runId
    && String(view.logical_channel_id) === String(channelId));

  return (
    <RailSection
      title="Link wait / Tx split"
      note="Measured per-link wait segments from this run's sampled-counters artifact. Window aggregates, not cycle playback."
    >
      <From
        origin="MEASURED"
        artifact="run"
        note={runId ? `link split bound to run ${runId}` : 'no run selected'}
        data={data}
      />
      {(runId == null || channelId == null) && (
        <p className="muted" role="status">Select an executed run and a measured link to read its split.</p>
      )}
      {runId != null && channelId != null && link.result.state === 'loading' && (
        <p className="muted" role="status">reading link split for channel {channelId}…</p>
      )}
      {runId != null && channelId != null && link.result.state === 'error' && (
        <p className="warn" role="alert">
          {(() => {
            const e = link.result.error;
            if (!(e instanceof ApiError)) return e.message;
            return e.message.startsWith(`${e.code}:`) ? e.message : `${e.code}: ${e.message}`;
          })()}
          {' '}— this run has no readable split for the channel; nothing is substituted.
        </p>
      )}
      {identityMatches && view && (
        <>
          <Kv label="channel" value={<code>{view.logical_channel_id}</code>} />
          <Kv label="utilization" value={`${(view.utilization * 100).toFixed(2)}%`} mono />
          <Kv label="flits" value={view.total_flits.toLocaleString()} mono />
          {view.breakdown == null ? (
            <p className="warn" role="note">
              {view.breakdown_absence ?? 'The measured split is absent from this run.'}
              {' '}Stalls render as a named gap, never as zero.
            </p>
          ) : (
            <>
              <BreakdownBar view={view} />
              <Kv label="per-hop latency, mean" value={`${fmt(view.breakdown.per_hop_latency_mean_cycles)} cyc`} mono />
              <Kv label="per-hop latency, peak" value={`${fmt(view.breakdown.peak_per_hop_latency_cycles, 0)} cyc`} mono />
              <Kv label="queued flits, mean" value={fmt(view.breakdown.mean_queued_flits_per_output)} mono />
              <Kv label="queued flits, peak" value={`${fmt(view.breakdown.peak_queued_flits, 0)}`} mono />
              <Kv label="arb-wait, peak" value={`${fmt(view.breakdown.peak_arb_wait_cycles, 0)} cyc`} mono />
            </>
          )}
        </>
      )}
      {runId != null && channelId != null && link.result.state === 'ready'
        && view !== null && !identityMatches && (
        <p className="bad" role="alert">
          Link response is for run {view.run}, not displayed run {runId}; the split is withheld.
        </p>
      )}
    </RailSection>
  );
}

/** The run's hottest measured link by mean per-hop latency (highest
 *  utilization when no link carries the split). Null-safe: a run whose
 *  artifact predates the counters still names its busiest link, and the
 *  breakdown below renders the absence. */
export function HottestLinkBreakdown({ data, runId }: {
  data: LoomData | null;
  runId: string | null;
}): ReactElement {
  const load = useAsync(
    () => (runId ? api.simLoad(runId) : Promise.resolve(null)),
    [runId],
  );
  const [channelId, setChannelId] = useState<string | null>(null);
  const rows = load.result.state === 'ready' ? load.result.data?.channels ?? [] : [];
  useEffect(() => { setChannelId(null); }, [runId]);
  useEffect(() => {
    if (channelId != null || rows.length === 0) return;
    let best = rows[0];
    for (const row of rows) {
      const latency = row.per_hop_latency_mean_cycles;
      const bestLatency = best.per_hop_latency_mean_cycles;
      if (latency != null && (bestLatency == null || latency > bestLatency)) best = row;
    }
    setChannelId(String(best.logical_channel_id));
  }, [rows, channelId]);
  if (runId == null) {
    return <p className="muted" role="status">No executed run — nothing measured.</p>;
  }
  if (load.result.state === 'loading') {
    return <p className="muted" role="status">reading measured links for run {runId}…</p>;
  }
  if (load.result.state === 'error') {
    const e = load.result.error;
    const text = e instanceof ApiError
      ? (e.message.startsWith(`${e.code}:`) ? e.message : `${e.code}: ${e.message}`)
      : e.message;
    return <p className="warn" role="alert">{text} — no measured waits are substituted.</p>;
  }
  if (rows.length === 0) {
    return <p className="muted" role="status">No measured links sampled for run {runId}.</p>;
  }
  return (
    <>
      <p className="loom-note">
        Auto-selected: highest mean per-hop latency among this run's sampled
        links — not necessarily a busiest link.
      </p>
      <SimLinkBreakdown data={data} runId={runId} channelId={channelId} />
    </>
  );
}
