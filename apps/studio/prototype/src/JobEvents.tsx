import { useEffect, useState } from 'react';
import { gateway, type JobLog } from './gateway';
import { useProject } from './project';
import { Badge, Button, Notice, Section } from './ui';

type StateEvent = { observedAt: string; state: string; message: string };
const TERMINAL = ['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'];

function LogTail({ jobId }: { jobId: string }) {
  const { health } = useProject();
  const enabled = health?.features?.job_logs === true;
  const [lines, setLines] = useState<string[]>([]), [meta, setMeta] = useState<JobLog | null>(null);
  const [error, setError] = useState(''), [retry, setRetry] = useState(0), [done, setDone] = useState(false), [offset, setOffset] = useState(0);
  useEffect(() => {
    if (!enabled || !jobId) return;
    setLines([]); setMeta(null); setError(''); setDone(false); setOffset(0);
    let closed = false;
    const stream = new EventSource(gateway.jobLogEventsUrl(jobId));
    stream.addEventListener('log', event => {
      try {
        const record = JSON.parse((event as MessageEvent).data) as JobLog;
        if (record.job_id !== jobId) throw new Error('Unexpected job log record.');
        setMeta(record);
        setOffset(record.next_offset);
        if (record.text) setLines(current => [...current, ...record.text.split(/\r?\n/).filter(Boolean)].slice(-500));
      } catch { setError('Invalid job-log event; stream stopped.'); closed = true; stream.close(); }
    });
    stream.addEventListener('end', () => { setDone(true); closed = true; stream.close(); });
    stream.onerror = () => {
      if (closed) return;
      setError('Job-log stream disconnected. The job may still be running; reconnect to tail from the last offset.');
      closed = true; stream.close();
    };
    return () => { closed = true; stream.close(); };
  }, [jobId, enabled, retry]);
  if (!enabled) return <Notice tone="amber">This gateway does not expose job logs.</Notice>;
  const resume = () => {
    if (done) { setRetry(n => n + 1); return; }
    // Reconnect through a fresh EventSource; the server starts at offset 0,
    // but the visible tail is bounded and the job log is terminal-readable.
    setRetry(n => n + 1);
  };
  return <Section title="Worker log" actions={meta ? <span className="mono">{offset} / {meta.size} bytes</span> : null}>
    {error && <><Notice tone="amber">{error}</Notice><Button onClick={resume}>Reconnect log</Button></>}
    {meta && !meta.available && !error && <Notice tone="amber">{meta.note ?? 'No worker log has been written yet.'}</Notice>}
    <pre className="code-preview job-log" aria-label="Job worker log">{lines.length ? lines.join('\n') : 'Waiting for worker output…'}</pre>
    {done && <p><small>Log stream ended at {meta?.size ?? 0} bytes with state {meta?.state ?? 'terminal'}.</small></p>}
  </Section>;
}

export function JobEvents({ jobId, state = '' }: { jobId: string; state?: string }) {
  const { health } = useProject();
  const enabled = health?.features?.job_events === true;
  const [events, setEvents] = useState<StateEvent[]>([]), [error, setError] = useState(''), [retry, setRetry] = useState(0), [open, setOpen] = useState(!TERMINAL.includes(state));
  useEffect(() => {
    if (!enabled || !jobId) return;
    setEvents([]); setError('');
    const stream = new EventSource(gateway.jobEventsUrl(jobId));
    stream.addEventListener('job', event => {
      try {
        const record = JSON.parse((event as MessageEvent).data);
        if (record.job_id !== jobId || typeof record.state !== 'string') throw new Error('Unexpected job event.');
        setEvents(rows => [...rows, { observedAt: new Date().toISOString(), state: record.state, message: record.error_message ?? '' }].slice(-100));
        if (TERMINAL.includes(record.state)) stream.close();
      } catch { setError('Invalid job event; stream stopped.'); stream.close(); }
    });
    stream.onerror = () => { setError('Job event stream disconnected.'); stream.close(); };
    return () => stream.close();
  }, [jobId, enabled, retry]);
  const latest = events[events.length - 1];
  useEffect(() => { if (state && TERMINAL.includes(state)) setOpen(false); }, [state]);
  useEffect(() => { if (latest && TERMINAL.includes(latest.state)) setOpen(false); }, [latest?.state]);
  if (!enabled || !jobId) return null;
  return <details className="study-diagnostics" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><span>Job diagnostics</span><span>{latest?.state ?? 'Waiting'} · state changes and worker log</span></summary>
    <Section title="Observed job states" actions={<Badge>{events.length}/100</Badge>}>{error && <><Notice tone="amber">{error}</Notice><Button onClick={() => setRetry(n => n + 1)}>Reconnect events</Button></>}<div className="table-scroll"><table><thead><tr><th>Observed at</th><th>State</th><th>Message</th></tr></thead><tbody>{events.map((record, index) => <tr key={index}><td className="mono">{record.observedAt}</td><td>{record.state}</td><td>{record.message || '—'}</td></tr>)}</tbody></table></div></Section>
    <LogTail jobId={jobId} />
  </details>;
}
