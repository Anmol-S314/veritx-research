import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { LoadedProject } from './project';
import { useLoadedRun, useProject } from './project';
import { Assumptions, Badge, Button, Icon, PageLink, Section } from './ui';
import { DraftContext, DraftSaveBar, IssueList, draftSchema, optionalNumber, useDraftSave, type Draft } from './draftSave';
import { num, shortText, stamp } from './format';
import { runVersionLabels } from './runLabel';
import type { IntentSaveState } from './intent';

const QOS_CLASSES = ['latency_critical', 'bandwidth', 'best_effort'];
const APPLICABILITY = ['APPLICABLE', 'NOT_APPLICABLE', 'NOT_EVALUATED'];
const TRAFFIC_CLASS_SUGGESTIONS = ['tp_collective', 'ep_dispatch', 'tp_reduce', 'ep_combine'];

type RequirementRow = {
  traffic_class: string;
  qos_class: string;
  binding: boolean;
  latency: string;
  bandwidth: string;
  applicability: string;
};

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

function fromRequest(request: Draft | null): RequirementRow[] {
  const rows = Array.isArray(request?.requirements) ? request!.requirements as Draft[] : [];
  return rows.map(row => ({
    traffic_class: text(row.traffic_class),
    qos_class: text(row.qos_class) || 'best_effort',
    binding: row.binding === true,
    latency: text(row.latency_ceiling_cycles),
    bandwidth: text(row.bandwidth_floor_gbps),
    applicability: text(row.applicability) || 'APPLICABLE',
  }));
}

function requirementIssues(rows: RequirementRow[]): string[] {
  const issues: string[] = [];
  rows.forEach((row, index) => {
    const where = `Criterion ${index + 1}`;
    if (!QOS_CLASSES.includes(row.qos_class)) issues.push(`${where}: choose a QoS class.`);
    if (!APPLICABILITY.includes(row.applicability)) issues.push(`${where}: choose an applicability.`);
    const latency = optionalNumber(row.latency);
    const bandwidth = optionalNumber(row.bandwidth);
    if (row.latency.trim() !== '' && (latency === null || latency < 0)) issues.push(`${where}: the latency ceiling must be a non-negative number.`);
    if (row.bandwidth.trim() !== '' && (bandwidth === null || bandwidth < 0)) issues.push(`${where}: the bandwidth floor must be a non-negative number.`);
    if (row.binding && latency === null && bandwidth === null) issues.push(`${where}: a bound criterion needs a latency ceiling or a bandwidth floor.`);
    if (row.binding && row.applicability === 'NOT_APPLICABLE' && (latency !== null || bandwidth !== null)) issues.push(`${where}: a waived criterion cannot also keep a bounded ceiling or floor.`);
  });
  return issues;
}

function buildRequest(base: Draft, rows: RequirementRow[]): Draft {
  const requirements = rows.map(row => {
    const doc: Draft = {
      traffic_class: row.traffic_class.trim() || null,
      qos_class: row.qos_class,
      latency_ceiling_cycles: optionalNumber(row.latency),
      bandwidth_floor_gbps: optionalNumber(row.bandwidth),
      binding: row.binding,
    };
    if (row.applicability !== 'APPLICABLE') doc.applicability = row.applicability;
    return doc;
  });
  return { ...base, requirements };
}

function verdictTone(value: string) {
  if (/SATISF|PASS/i.test(value)) return 'green' as const;
  if (/VIOL|FAIL/i.test(value)) return 'red' as const;
  return 'amber' as const;
}

export function LiveRequirementsPage({ project, notify, embedded = false, onDirty, onSaveState, footer }: {
  project: LoadedProject;
  notify: (message: string) => void;
  embedded?: boolean;
  onDirty?: (dirty: boolean) => void;
  onSaveState?: (state: IntentSaveState) => void;
  /** Rendered after the criteria and before the assumptions, so the flow can
   *  keep its actions in one place without splitting the scope block. */
  footer?: ReactNode;
}) {
  const request = project.request as Draft | null;
  const baseline = useMemo(() => fromRequest(request), [request]);
  const [rows, setRows] = useState<RequirementRow[]>(baseline);
  useEffect(() => { setRows(baseline); }, [baseline]);
  const saveState = useDraftSave(project, notify);
  const saveRef = useRef<() => void>(() => {});
  const run = useLoadedRun();
  const { loadRun } = useProject();
  const verdicts = run?.detail.requirements?.entries ?? [];
  const schema = draftSchema(project);
  const readOnly = schema !== null && schema >= 5;
  const collectives = (request?.workload?.collectives ?? []) as Draft[];
  const activeRevisionId = project.detail.active_revision_id;
  const activeRun = [...(project.detail.runs ?? [])]
    .filter(entry => entry.revision_id === activeRevisionId)
    .sort((a, b) => String(b.completed_at ?? '').localeCompare(String(a.completed_at ?? '')))[0] ?? null;
  const runLabels = runVersionLabels(project.detail.runs ?? []);
  const selectedRunLabel = run ? runLabels.get(run.detail.run_id) ?? shortText(run.detail.run_id, 16) : '—';
  const activeRunLabel = activeRun ? runLabels.get(activeRun.run_id) ?? shortText(activeRun.run_id, 13) : '';
  const runIsActive = !!run && run.detail.revision_id === activeRevisionId;

  const dirty = JSON.stringify(rows) !== JSON.stringify(baseline);
  useEffect(() => { onDirty?.(dirty); }, [dirty, onDirty]);
  const issues = requirementIssues(rows);
  const valid = issues.length === 0;
  const trafficClasses = [...new Set(collectives
    .map(row => text(row.traffic_class).trim())
    .filter(Boolean))];
  const trafficClassOptions = [...new Set([...trafficClasses, ...TRAFFIC_CLASS_SUGGESTIONS])];
  const criterionClasses = new Set(rows.map(row => row.traffic_class.trim()).filter(Boolean));
  const uncoveredTraffic = trafficClasses.filter(name => !criterionClasses.has(name));
  const unmatchedCriteria = [...criterionClasses].filter(name => !trafficClasses.includes(name));
  const matched = rows.filter(row => verdicts.some(verdict => verdict.traffic_class === row.traffic_class.trim() && verdict.qos_class === row.qos_class)).length;

  const patch = (index: number, change: Partial<RequirementRow>) => setRows(current =>
    current.map((row, position) => position === index ? { ...row, ...change } : row));
  const add = () => setRows(current => [...current, {
    traffic_class: uncoveredTraffic[0] ?? '',
    qos_class: 'latency_critical',
    binding: false,
    latency: '',
    bandwidth: '',
    applicability: 'APPLICABLE',
  }]);
  const save = () => saveState.save(base => buildRequest(base, rows), 'Requirements saved to the draft. Compile and evaluate to produce new verdicts.');
  saveRef.current = save;
  useEffect(() => {
    onSaveState?.({
      dirty,
      valid: valid && !readOnly,
      busy: saveState.busy,
      error: saveState.error,
      save: () => saveRef.current(),
    });
  }, [dirty, valid, readOnly, saveState.busy, saveState.error, onSaveState]);

  return <div className={embedded ? 'studio-embedded' : 'view-main studio-view'}>
    {!embedded && <DraftContext project={project} />}
    {embedded && <h2 className="studio-embedded-title">Acceptance criteria</h2>}
    {!embedded && <div className="studio-intro">
      <div>
        <h2>Acceptance criteria</h2>
      </div>
      <PageLink page="workloads/lowering">Next: validate <Icon name="arrow" /></PageLink>
    </div>}

    {run
      ? <div className={runIsActive ? 'inline-note' : 'inline-note amber'}>
        <Badge tone={runIsActive ? 'green' : 'amber'}>{runIsActive ? 'Active revision' : 'Historical run'}</Badge>{' '}
        <strong>Verdicts from run <code>{selectedRunLabel}</code> on revision <code>{run.detail.revision_id}</code>.</strong>{' '}
        <span className="muted mono">({shortText(run.detail.run_id, 16)})</span>{' '}
        {run.detail.completed_at ? `Completed ${stamp(run.detail.completed_at)}. ` : ''}
        {runIsActive
          ? 'This run is on the active revision.'
          : <>This run is historical; the active revision is <code>{activeRevisionId ?? 'none'}</code>. Verdicts describe the run and revision, not the current draft.</>}
        {!runIsActive && <div className="actions" style={{ marginTop: 6 }}>
          {activeRun
            ? <Button primary onClick={() => loadRun(activeRun.run_id)}>Open active revision run · {activeRunLabel}</Button>
            : <PageLink page="analysis/summary" primary>Evaluate active revision</PageLink>}
        </div>}
      </div>
      : <div className="inline-note"><strong>No run selected.</strong> No verdict is inferred.{' '}
        {activeRun
          ? <Button primary onClick={() => loadRun(activeRun.run_id)}>Open active revision run · {activeRunLabel}</Button>
          : <PageLink page="analysis/summary" primary>Evaluate active revision</PageLink>}
      </div>}

    {!!(uncoveredTraffic.length || unmatchedCriteria.length) && <div className="inline-note amber">
      {uncoveredTraffic.length > 0 && <>Traffic declared without a criterion: <span className="mono">{uncoveredTraffic.join(', ')}</span>. </>}
      {unmatchedCriteria.length > 0 && <>Criterion without declared traffic: <span className="mono">{unmatchedCriteria.join(', ')}</span>. </>}
      <a href="#/workloads/library">Review declared traffic</a>.
    </div>}

    <Section title="Criteria" actions={rows.length ? <Button onClick={add}><Icon name="plus" />Add criterion</Button> : undefined}>
      <datalist id="requirement-traffic-classes">
        {trafficClassOptions.map(option => <option key={option} value={option} />)}
      </datalist>
      {rows.length ? <div className="table-scroll"><table className="editor-table criteria-table">
        <colgroup>
          <col className="criteria-col-class" /><col className="criteria-col-qos" /><col className="criteria-col-binding" />
          <col className="criteria-col-value" /><col className="criteria-col-value" /><col className="criteria-col-applicability" />
          <col className="criteria-col-verdict" /><col className="criteria-col-action" />
        </colgroup>
        <thead><tr><th>Traffic class</th><th>QoS class</th><th>Binding</th><th>Latency ceiling <small>cycles</small></th><th>Bandwidth floor <small>GB/s</small></th><th>Applicability</th><th>Verdict</th><th /></tr></thead>
        <tbody>
          {rows.map((row, index) => {
            const verdict = verdicts.find(entry => entry.traffic_class === row.traffic_class.trim() && entry.qos_class === row.qos_class);
            return <tr key={index}>
              <td><input aria-label={`criterion ${index + 1} traffic class`} list="requirement-traffic-classes" value={row.traffic_class} placeholder="Choose or type a class" onChange={event => patch(index, { traffic_class: event.target.value })} /></td>
              <td><select aria-label={`criterion ${index + 1} qos`} value={row.qos_class} onChange={event => patch(index, { qos_class: event.target.value })}>
                {!QOS_CLASSES.includes(row.qos_class) && <option value={row.qos_class}>{row.qos_class} (unsupported here)</option>}
                {QOS_CLASSES.map(qos => <option key={qos} value={qos}>{qos}</option>)}
              </select></td>
              <td className="check-cell"><input aria-label={`criterion ${index + 1} binding`} type="checkbox" checked={row.binding} onChange={event => patch(index, { binding: event.target.checked })} /></td>
              <td><input aria-label={`criterion ${index + 1} latency ceiling`} type="number" min={0} step="any" value={row.latency} placeholder="cycles" onChange={event => patch(index, { latency: event.target.value })} /></td>
              <td><input aria-label={`criterion ${index + 1} bandwidth floor`} type="number" min={0} step="any" value={row.bandwidth} placeholder="GB/s" onChange={event => patch(index, { bandwidth: event.target.value })} /></td>
              <td><select aria-label={`criterion ${index + 1} applicability`} value={row.applicability} onChange={event => patch(index, { applicability: event.target.value })}>
                {!APPLICABILITY.includes(row.applicability) && <option value={row.applicability}>{row.applicability} (unsupported here)</option>}
                {APPLICABILITY.map(value => <option key={value} value={value}>{value}</option>)}
              </select></td>
              <td className="verdict-cell">{verdict
                ? <><Badge tone={verdictTone(String(verdict.verdict))}>{verdict.verdict ?? 'VERDICT'}</Badge>
                  <small>{verdict.measured === null || verdict.measured === undefined ? 'No measurement' : `measured ${num(verdict.measured)}`}{verdict.required !== null && verdict.required !== undefined ? ` · required ${verdict.required}` : ''}</small>
                  {verdict.reason && <small className="verdict-reason">{verdict.reason}</small>}</>
                : <Badge tone="amber">No verdict</Badge>}</td>
              <td><Button onClick={() => setRows(current => current.filter((_, position) => position !== index))}>Remove</Button></td>
            </tr>;
          })}
        </tbody>
      </table></div> : <div className="callout">
        <div><strong>No criteria declared.</strong><p>The draft still compiles, but no pass or fail can be produced without at least one criterion.</p></div>
        <Button primary onClick={add}><Icon name="plus" />Add the first criterion</Button>
      </div>}
    </Section>

    {readOnly && <div className="inline-note amber"><strong>Schema v{schema} draft.</strong> This page reads the flat criteria block and will not rewrite nested v5 intent. Use the Project workflow draft editor.</div>}
    <IssueList issues={issues} />
    {!embedded && <DraftSaveBar dirty={dirty} valid={valid && !readOnly} state={saveState} onSave={save} note="Criteria changes do not rewrite an existing run's verdicts." />}
    {footer}
    <Assumptions rows={[
      ['Verdict source', run ? `run ${selectedRunLabel} (${shortText(run.detail.run_id, 16)}) on ${run.detail.revision_id}` : 'no run loaded'],
      ['Measured here', 'Nothing; this page declares criteria and reads an existing run.'],
      ['Binding', 'A bound criterion must declare a latency ceiling or bandwidth floor.'],
      ['Not evaluated', 'Missing measurement or missing execution scope; never shown as a pass.'],
      ['Classes', 'A traffic class is shared by one or more collectives, so another collective under an existing class does not add a distinct class.'],
      ['Verdict coverage', `${matched}/${rows.length} criteria matched a verdict in the loaded run; a matched verdict can be UNMEASURABLE, which is not a pass.`],
      ['Scope', 'Declarative criteria only; not a compile, simulation or qualification.'],
    ]}>
      <PageLink page="verify/evidence">Inspect the evidence bundle</PageLink>
    </Assumptions>
  </div>;
}
