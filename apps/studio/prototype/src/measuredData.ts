import { useEffect, useState } from 'react';
import { gateway, gatewayReason, type SimLoad, type SimSeries } from './gateway';

export type MeasuredState<T> = {
  phase: 'loading' | 'ready' | 'absent' | 'error';
  data?: T;
  reason?: string;
};

const absent = /NO_MEASURED|no sampled series/i;

// Several measured sections read the same run. The cache keeps one request per
// run per artifact; failed requests are evicted so a remount can retry.
const loadRequests = new Map<string, Promise<SimLoad>>();
const seriesRequests = new Map<string, Promise<SimSeries>>();

function requestLoad(runId: string): Promise<SimLoad> {
  const cached = loadRequests.get(runId);
  if (cached) return cached;
  const request = gateway.simLoad(runId);
  loadRequests.set(runId, request);
  request.catch(() => { if (loadRequests.get(runId) === request) loadRequests.delete(runId); });
  return request;
}

function requestSeries(runId: string): Promise<SimSeries> {
  const cached = seriesRequests.get(runId);
  if (cached) return cached;
  const request = gateway.simSeries(runId);
  seriesRequests.set(runId, request);
  request.catch(() => { if (seriesRequests.get(runId) === request) seriesRequests.delete(runId); });
  return request;
}

function useMeasured<T>(runId: string, request: (runId: string) => Promise<T>): MeasuredState<T> {
  const [state, setState] = useState<MeasuredState<T>>({ phase: 'loading' });
  useEffect(() => {
    let live = true;
    // Callers pass '' to keep a section dormant (drawer closed, no run chosen).
    // That is not a request for run "", which the gateway answers with a 404.
    if (!runId) { setState({ phase: 'loading' }); return () => { live = false; }; }
    setState({ phase: 'loading' });
    request(runId)
      .then(data => { if (live) setState({ phase: 'ready', data }); })
      .catch(error => {
        if (!live) return;
        const reason = gatewayReason(error);
        setState({ phase: absent.test(reason) ? 'absent' : 'error', reason });
      });
    return () => { live = false; };
  }, [runId, request]);
  return state;
}

export const useSimLoad = (runId: string) => useMeasured(runId, requestLoad);
export const useSimSeries = (runId: string) => useMeasured(runId, requestSeries);
