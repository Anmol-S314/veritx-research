import type { ReactElement } from 'react';
import type {
  CompileCertificate, CompileResultView, PreflightView,
} from '../../api';
import { fmtNum } from '../badges';
import { deadlockMessage } from './deadlock';

export default function EngineeringFindings({ result, preflight,
  certificate }: {
  result: CompileResultView;
  preflight: PreflightView | null;
  certificate: CompileCertificate | null;
}): ReactElement {
  const groups = result.groups;
  const findings: { text: string; tone: string }[] = [];
  if (!groups) return <></>;
  const derived = groups.summary.derived;
  const declared = groups.summary.declared;
  const idle = (derived.seats ?? 0) - (derived.endpoints ?? 0);
  const consequences = result.capability_consequences ?? [];

  if (idle > 0) {
    findings.push({
      text: `${fmtNum(idle)} unused fabric seats — the fabric is ` +
        `larger than the workload needs (${fmtNum(derived.seats)} seats, ` +
        `${fmtNum(derived.endpoints)} endpoints attached).`,
      tone: 'muted',
    });
  }
  if ((derived.vc_count ?? 0) <= 1) {
    findings.push({
      text: `Routing uses a single VC — no escape resource is required, `
        + `and there is no adaptive VC to inspect.`,
      tone: 'muted',
    });
  }
  if ((groups.address_decode.rows ?? []).length === 0) {
    findings.push({
      text: `The address map is empty — every access uses the identity `
        + `transform and unmatched addresses error.`,
      tone: 'muted',
    });
  }
  const deadlockText = deadlockMessage(
    certificate?.deadlock_analysis ?? undefined).text;
  findings.push({ text: deadlockText, tone: 'muted' });
  for (const c of consequences) {
    if (c.capability_id === 'COMM-006'
        && (c.wiring === 'NOT_AVAILABLE'
            || /not.available|unavailable/i.test(c.reason ?? ''))) {
      continue;
    }
    findings.push({
      text: `${c.capability_id}: ${c.choice} — ${c.wiring}`
        + (c.reason ? ` (${c.reason})` : ''),
      tone: 'muted',
    });
  }
  if (preflight && !preflight.ready) {
    findings.push({
      text: `Backend execution is ${preflight.ready ? 'available' : 'blocked'}`
        + (preflight.reason ? `: ${preflight.reason}` : ''),
      tone: preflight.ready ? 'ok' : 'bad',
    });
  } else if (preflight?.ready) {
    findings.push({
      text: `Backend execution is available via ${preflight.backend}.`,
      tone: 'ok',
    });
  }
  if ((declared.concentration ?? 1) > 1) {
    findings.push({
      text: `Concentrated fabric (concentration ${declared.concentration}) `
        + `is valid — executability depends on the certified profile, see `
        + `Can I run this?`,
      tone: 'muted',
    });
  }

  const classes = derived.routing_classes ?? [];
  if (classes.length > 1) {
    findings.push({
      text: `Multi-class workload (${classes.join(', ')}) — multi-class ` +
        `BookSim execution is qualified under the multi-class envelope; ` +
        `see Execution availability.`,
      tone: 'muted',
    });
  }
  if (findings.length === 0) {
    return <></>;
  }
  return (
    <section className="card" aria-label="Important consequences">
      <h4>Important consequences</h4>
      <ul className="finding-list">
        {findings.map((f, i) => (
          <li key={i} className={f.tone}>{f.text}</li>
        ))}
      </ul>
    </section>
  );
}
