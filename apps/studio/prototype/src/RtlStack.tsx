import { useEffect, useState } from 'react';
import { gateway, gatewayReason, type FinalImplementationEvidence, type RtlReadiness, type RtlSourcesView } from './gateway';
import type { LoadedProject } from './project';
import { evidenceFamilyKey } from './finalEvidence';
import { Badge, Notice, Properties, Section } from './ui';

type Tone = 'green' | 'amber' | 'neutral' | 'red';
type StageState = 'recorded' | 'partial' | 'not run' | 'blocked';
type Stage = {
  id: string;
  stage: string;
  mechanism: string;
  state: StageState;
  tone: Tone;
  detail: string;
  evidence?: React.ReactNode;
};

const TONE: Record<StageState, Tone> = { recorded: 'green', partial: 'amber', 'not run': 'neutral', blocked: 'red' };

type Documents = {
  sources?: RtlSourcesView;
  readiness?: RtlReadiness;
  prototypes?: { counts?: { required_total?: number; required_present?: number; required_missing_or_unknown?: number }; prototypes?: { lint_status?: string; simulation_status?: string }[] };
  deferred?: Record<string, string>;
  finalEvidence?: FinalImplementationEvidence;
  reasons: string[];
};

/** One place that names the whole hardware path the product does and does not
 *  cover: generator source, emitted RTL, front-end checks, synthesis, place and
 *  route, signoff. Only gateway-recorded facts get a positive state; the rest
 *  are shown as unrecorded rather than inferred. */
export function RtlStack({ project }: { project: LoadedProject }) {
  const id = project.detail.project.project_id;
  const revision = project.detail.active_revision_id;
  const [docs, setDocs] = useState<Documents>({ reasons: [] });
  const [phase, setPhase] = useState<'loading' | 'ready'>('loading');

  useEffect(() => {
    let live = true;
    setPhase('loading');
    const read = async () => {
      const [sources, readiness, prototypes, capabilities, finalEvidence] = await Promise.allSettled([
        gateway.rtlSources(),
        gateway.rtlReadiness(id),
        gateway.rtlPrototypes(),
        gateway.capabilities(),
        gateway.finalImplementation(),
      ]);
      if (!live) return;
      setDocs({
        sources: sources.status === 'fulfilled' ? sources.value : undefined,
        readiness: readiness.status === 'fulfilled' ? readiness.value : undefined,
        prototypes: prototypes.status === 'fulfilled' ? prototypes.value : undefined,
        deferred: capabilities.status === 'fulfilled' ? (capabilities.value.deferred as Record<string, string> | undefined) : undefined,
        finalEvidence: finalEvidence.status === 'fulfilled' ? finalEvidence.value : undefined,
        reasons: [sources, readiness, prototypes, capabilities]
          .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
          .map(result => gatewayReason(result.reason)),
      });
      setPhase('ready');
    };
    void read().catch(caught => {
      if (!live) return;
      setDocs({ reasons: [gatewayReason(caught)] });
      setPhase('ready');
    });
    return () => { live = false; };
  }, [id, revision]);

  const sources = docs.sources;
  const readiness = docs.readiness;
  const support = readiness?.preview_support;
  const prototypeRows = docs.prototypes?.prototypes ?? [];
  const prototypePresent = docs.prototypes?.counts?.required_present ?? prototypeRows.filter(row => row.lint_status && row.lint_status !== 'NOT_RUN').length;
  const prototypeTotal = docs.prototypes?.counts?.required_total ?? prototypeRows.length;
  const lintPassed = prototypeRows.filter(row => /PASS|CLEAN/i.test(String(row.lint_status))).length;
  const simPassed = prototypeRows.filter(row => /PASS/i.test(String(row.simulation_status))).length;
  const finalFlag = readiness?.final_rtl_available === true;
  const familyKey = evidenceFamilyKey(support, project.request as Record<string, unknown> | null);
  const familyEvidence = docs.finalEvidence?.families.find(row => row.family === familyKey) ?? null;
  const selectedDesignHash = readiness?.draft_design_hash?.replace(/^sha256:/i, '') ?? null;
  const familyMatches = !!familyEvidence?.design_hash && !!selectedDesignHash && familyEvidence.design_hash === selectedDesignHash;
  const composed = readiness?.composed_family_preflight ?? null;
  const familyLint = familyEvidence?.measured?.A1 as { lint?: string; sim?: string } | undefined;
  const familyScenarios = familyEvidence?.measured?.A2 as { scenarios?: number; lint?: string; sim?: string } | undefined;

  const stages: Stage[] = [
    {
      id: 'source', stage: '1 · Source', mechanism: 'Chipyard / Constellation generators',
      state: sources?.available ? 'recorded' : sources?.integration_present ? 'partial' : sources ? 'blocked' : 'not run',
      tone: TONE[sources?.available ? 'recorded' : sources?.integration_present ? 'partial' : sources ? 'blocked' : 'not run'],
      detail: sources
        ? sources.available
          ? `${sources.source_file_count} source files across ${sources.target_count} topology targets. ${sources.matches_selected_project ? 'The selected project matches this source.' : 'The inventory is not bound to this project revision.'}`
          : `${sources.integration_present
            ? 'Repository integration is present (dispatcher, parameterized core, KNCube exporter and KNCube test).'
            : 'The repository integration is incomplete.'} ${sources.exporters_present ?? 0} of ${sources.exporters_total ?? sources.target_count} family exporters are available across the repository and external trees. ${(sources.missing_exporters ?? []).length
              ? `Missing: ${(sources.missing_exporters ?? []).join(', ')}.`
              : 'Every family exporter source is present.'} ${sources.license_present === false
              ? 'The external source tree has no LICENSE file, so the all-target archive is not assembled.'
              : 'The assembled archive is not available; see the inventory reason.'} The product emitter does not read the external tree.`
        : phase === 'loading' ? 'Reading the source inventory…' : 'The source inventory could not be read.',
      evidence: sources?.available
        ? <>
          <a className="button" href={gateway.rtlSourcesArchiveUrl()} download>Chipyard / Constellation archive</a>
          {readiness?.parameterized_source_available && revision && <a className="button" href={gateway.revisionChipyardSourceArchiveUrl(revision)} download>This revision's Chipyard source</a>}
        </>
        : sources?.integration_present ? <Badge tone="amber">Integration only</Badge> : undefined,
    },
    {
      id: 'emit', stage: '2 · Emit', mechanism: 'Product RTL emitter',
      state: support?.supported ? 'partial' : readiness ? 'blocked' : 'not run',
      tone: support?.supported ? 'amber' : readiness ? 'red' : 'neutral',
      detail: readiness
        ? support?.supported
          ? `${support.code} · ${support.topology_family ?? support.topology_kind ?? 'topology'} · ${support.router_count ?? '—'} routers · ${support.emitted_vcs} emitted VC${support.emitted_vcs === 1 ? '' : 's'}${support.vc_count != null && support.vc_count !== support.emitted_vcs ? ` vs ${support.vc_count} measured` : ''}. This selected-project path is a topology-only preview and does not carry the final-implementation flag; composed-family evidence is reported separately below.`
          : readiness.final_rtl_reason
        : phase === 'loading' ? 'Reading this revision’s RTL readiness…' : 'RTL readiness could not be read.',
      evidence: support?.supported ? <Badge tone={finalFlag ? 'green' : 'amber'}>{finalFlag ? 'Final RTL recorded' : 'Preview scope'}</Badge> : undefined,
    },
    {
      id: 'lint', stage: '3 · Check', mechanism: 'Verilator lint · Icarus / Verilator simulation',
      state: lintPassed || simPassed ? 'partial' : 'not run',
      tone: lintPassed || simPassed ? 'amber' : 'neutral',
      detail: prototypeTotal
        ? `The research file-presence registry reports ${prototypePresent} of ${prototypeTotal} targets in its configured root · ${lintPassed} lint pass · ${simPassed} simulation pass. A preview job records its own lint result; no check result is attached to this revision here.`
        : 'No recorded lint or simulation result is attached to this revision. The preview emitter runs Verilator lint when a preview job is launched.',
    },
    {
      id: 'formal', stage: '4 · Prove', mechanism: 'SymbiYosys · Z3 bounded checks',
      state: docs.deferred?.formal_verification && docs.deferred.formal_verification !== 'NOT_RUN' ? 'partial' : 'not run',
      tone: docs.deferred?.formal_verification && docs.deferred.formal_verification !== 'NOT_RUN' ? 'amber' : 'neutral',
      detail: `Formal verification is ${docs.deferred?.formal_verification ?? 'not reported'} in the backend register. Bounded credit and routing proofs exist as research mechanisms; they are not a product-scoped formal result for this revision.`,
    },
    {
      id: 'synthesis', stage: '5 · Synthesize', mechanism: 'Yosys',
      state: docs.deferred?.rtl_verification && docs.deferred.rtl_verification !== 'NOT_RUN' ? 'partial' : 'not run',
      tone: docs.deferred?.rtl_verification && docs.deferred.rtl_verification !== 'NOT_RUN' ? 'amber' : 'neutral',
      detail: 'No mapped netlist or synthesis report is attached to this revision. Synthesis is a separate gate and is not implied by a successful lint or simulation.',
    },
    {
      id: 'physical', stage: '6 · Implement', mechanism: 'LibreLane · OpenROAD · Magic · Netgen · KLayout',
      state: 'not run', tone: 'neutral',
      detail: 'No placed, routed, timed or signoff result is attached to this revision. The LibreLane flow is configured against the Sky130A diagnostic platform; an implementation result requires an approved platform, constraints and a measured run.',
    },
    {
      id: 'signoff', stage: '7 · Deliver', mechanism: 'Manifest · UVM collateral · archives',
      state: revision ? 'partial' : 'blocked', tone: revision ? 'amber' : 'red',
      detail: revision
        ? `Revision ${revision} has a delivery manifest. RTL, UVM and physical qualification remain separate claims; the manifest states its own scope.`
        : 'Compile a revision before delivery artifacts exist.',
      evidence: readiness?.revision_id ? <Badge tone={readiness.final_rtl_available ? 'green' : 'amber'}>{readiness.final_rtl_available ? 'Final RTL available' : 'Preview only'}</Badge> : undefined,
    },
  ];

  return <Section title="RTL & implementation path" actions={<>
    <Badge tone={finalFlag ? 'green' : 'amber'}>{finalFlag ? 'Final RTL recorded' : 'Preview / research scope'}</Badge>
    {familyEvidence && <Badge tone={familyMatches ? 'green' : 'amber'}>{familyMatches ? 'Composed evidence bound' : `Composed evidence · ${familyEvidence.family}`}</Badge>}
    <Badge tone="neutral">Physical result not recorded</Badge>
  </>}>
    <ol className="rtl-stack-chain" aria-label="Implementation path">
      {['Source', 'Emit', 'Check', 'Prove', 'Synthesize', 'Implement', 'Deliver'].map((label, index) => <li key={label} className={stages[index]?.tone === 'green' ? 'recorded' : stages[index]?.tone === 'red' ? 'blocked' : ''}>
        <span>{label}</span>
        <small>{stages[index]?.state ?? 'not run'}</small>
      </li>)}
    </ol>

    {phase === 'loading' && <p role="status">Reading RTL source and implementation evidence…</p>}
    {docs.reasons.length > 0 && <Notice tone="amber">Some implementation documents could not be read: {docs.reasons.join(' · ')}</Notice>}

    <div className="table-scroll rtl-stack-table"><table>
      <thead><tr><th>Stage</th><th>Mechanism</th><th>State</th><th>Recorded evidence and boundary</th></tr></thead>
      <tbody>{stages.map(stage => <tr key={stage.id}>
        <th>{stage.stage}</th>
        <td>{stage.mechanism}</td>
        <td><Badge tone={stage.tone}>{stage.state}</Badge></td>
        <td>{stage.detail}{stage.evidence && <div className="rtl-stack-evidence">{stage.evidence}</div>}</td>
      </tr>)}</tbody>
    </table></div>

    {(familyEvidence || docs.finalEvidence?.errors?.length) && <Section title="Composed-family implementation evidence" actions={<Badge tone={familyEvidence?.final_implementation ? 'green' : 'amber'}>{familyEvidence ? (familyEvidence.final_implementation ? 'A1–A10 closed' : `${familyEvidence.open_rows.length} open`) : 'read error'}</Badge>}>
      {docs.finalEvidence?.errors?.length ? <Notice tone="amber">Some composed-family evidence files could not be read: {docs.finalEvidence.errors.join(' · ')}</Notice> : null}
      {familyEvidence && <>
        {composed?.blocker && <Notice tone="amber"><strong>Composed-family preflight is blocked for this revision.</strong> {composed.blocker}. The family evidence below belongs to a different design; no final RTL exists for this revision.</Notice>}
        <Properties rows={[
          ['Family', familyEvidence.family],
          ['Evidence design', <span className="mono">{familyEvidence.design_hash ?? 'not recorded'}</span>],
          ['This revision', <span className="mono">{selectedDesignHash ?? 'not reported'}</span>],
          ['Binding', familyMatches ? 'Same design hash' : 'Different design — evidence does not transfer'],
          ['Lint / scenarios', `${familyLint?.lint ?? familyScenarios?.lint ?? 'not recorded'} · ${familyScenarios?.scenarios ?? '—'} scenarios · simulation ${familyLint?.sim ?? familyScenarios?.sim ?? 'not recorded'}`],
          ['Source', <span className="mono">{familyEvidence.source}</span>],
        ]} />
        <Notice tone={familyMatches ? 'blue' : 'amber'}>
          <strong>{familyMatches ? 'This revision has composed-family evidence.' : 'Family-scoped evidence only.'}</strong>{' '}
          {familyMatches
            ? 'The A1–A10 rows are recorded for this exact design hash. This is still not physical implementation or signoff.'
            : `The ${familyEvidence.family} family has A1–A10 evidence for design ${familyEvidence.design_hash?.slice(0, 12) ?? '—'}…, not this revision (${selectedDesignHash?.slice(0, 12) ?? '—'}…). The preview above remains the only RTL path bound to this revision.`}
        </Notice>
      </>}
    </Section>}

    <details className="rtl-stack-details">
      <summary>LibreLane gate contract · what a physical run must measure</summary>
      <p className="meta-line">Reference flow: LibreLane 3.0.17 on the emitted design directory, with Sky130A as a diagnostic platform. The run is accepted only when every gate below has a measured value; an absent metric fails the run, and a staged run reports PARTIAL rather than signoff.</p>
      <div className="table-scroll"><table>
        <thead><tr><th>Gate</th><th>Metric</th><th>This revision</th></tr></thead>
        <tbody>
          <tr><th>Unmapped cells</th><td className="mono">design__instance_unmapped__count</td><td><Badge tone="neutral">Not measured</Badge></td></tr>
          <tr><th>Setup slack</th><td className="mono">timing__setup__ws · worst corner</td><td><Badge tone="neutral">Not measured</Badge></td></tr>
          <tr><th>Hold slack</th><td className="mono">timing__hold__ws · worst corner</td><td><Badge tone="neutral">Not measured</Badge></td></tr>
          <tr><th>DRC</th><td className="mono">pooled *drc*error* / *drc*violation*</td><td><Badge tone="neutral">Not measured</Badge></td></tr>
          <tr><th>LVS</th><td className="mono">pooled *lvs*</td><td><Badge tone="neutral">Not measured</Badge></td></tr>
          <tr><th>Antenna</th><td className="mono">pooled *antenna*violation*</td><td><Badge tone="neutral">Not measured</Badge></td></tr>
        </tbody>
      </table></div>
      <p className="meta-line">Tools in the flow: LibreLane, OpenROAD, Yosys, Verilator, Magic, Netgen, KLayout. Source: the design-bound physical runner in <span className="mono">tracks/t3-topology/dse/veritx_dse/product/physical_runner.py</span>.</p>
    </details>

    <details className="rtl-stack-details">
      <summary>Research RTL mechanisms in this repository</summary>
      <ul className="rtl-stack-list">
        <li><strong>Chipyard generators</strong> — native exporters for the 14 topology families, with a shared source tree and a standalone check harness.</li>
        <li><strong>Constellation sources</strong> — the catalog entry points are <span className="mono">constellation.veritx.*</span>; the gateway reports whether that tree is present instead of assuming it.</li>
        <li><strong>Emitted fabric RTL</strong> — the product emitter writes topology-only previews (address decode, ordering FSM, CDC cells, protocol adapters) from the compiled graph.</li>
        <li><strong>Verilator / Icarus</strong> — lint and simulation of the emitted RTL; results belong to the specific job and revision that produced them.</li>
        <li><strong>SBY / Z3</strong> — bounded proofs for credit conservation and routing research harnesses, not a whole-design formal claim.</li>
        <li><strong>Yosys</strong> — generic synthesis of the emitted design, ahead of any place-and-route attempt.</li>
        <li><strong>LibreLane / OpenROAD / Magic / Netgen / KLayout</strong> — the physical implementation and signoff path described above.</li>
      </ul>
    </details>

  </Section>;
}
