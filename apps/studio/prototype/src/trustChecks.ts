// Local, read-only trust checks over one recorded run.
//
// These checks do not decide that a model is correct. They find contradictions
// between the declared workload, the recorded evidence, and the reported
// metrics so a reader can see what still needs review. A passing check is not
// hardware qualification.
import type { DeclaredStage, DraftRequest, LoadedProject, LoadedRun } from './project';

export type TrustResult = 'PASS' | 'FAIL' | 'REVIEW' | 'UNKNOWN';

export type TrustCheck = {
  id: string;
  label: string;
  result: TrustResult;
  evidence: string;
  detail?: string;
};

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

function stageDuration(stage: DeclaredStage): number {
  return finite(stage.duration_ns) && stage.duration_ns > 0 ? stage.duration_ns : 0;
}

function parallelism(request: DraftRequest | null): { tp: number; dp: number; ep: number; pp: number; ranks: number } {
  const workload = request?.workload ?? {};
  const tp = finite(workload.tp) && workload.tp > 0 ? workload.tp : 1;
  const dp = finite(workload.dp) && workload.dp > 0 ? workload.dp : 1;
  const ep = finite(workload.ep) && workload.ep > 0 ? workload.ep : 1;
  const pp = finite(workload.pp) && workload.pp > 0 ? workload.pp : 1;
  return { tp, dp, ep, pp, ranks: tp * dp * ep * pp };
}

function stagesOf(request: DraftRequest | null): DeclaredStage[] {
  return Array.isArray(request?.compute?.stages) ? request.compute.stages : [];
}

function numberedLayers(stages: DeclaredStage[]): { layers: Map<number, Set<string>>; named: boolean } {
  const layers = new Map<number, Set<string>>();
  let named = stages.length > 0;
  for (const stage of stages) {
    const match = /^layer(\d+)_(attn|moe)$/i.exec(String(stage.stage_id ?? ''));
    if (!match) { named = false; continue; }
    const layer = Number(match[1]);
    const kind = match[2].toLowerCase();
    const set = layers.get(layer) ?? new Set<string>();
    set.add(kind);
    layers.set(layer, set);
  }
  return { layers, named };
}

function analysisByQuestion(run: LoadedRun, question: string) {
  return (run.detail.analyses ?? []).find(analysis => analysis.question === question) ?? null;
}

function metricValue(analysis: { normalized_metrics?: { key?: string; value?: number | null }[] } | null, key: string): number | null {
  const metric = analysis?.normalized_metrics?.find(item => item.key === key);
  return finite(metric?.value) ? metric.value : null;
}

function seconds(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 3 })} ns`;
}

function makespanCheck(stages: DeclaredStage[], run: LoadedRun, placementDistributed: boolean): TrustCheck {
  const analysis = analysisByQuestion(run, 'SYSTEM_MAKESPAN');
  const native = (analysis?.native_summary ?? {}) as Record<string, unknown>;
  const aggregate = finite(native.aggregate_cycles) ? native.aggregate_cycles : null;
  const exposed = finite(native.aggregate_exposed_comm) ? native.aggregate_exposed_comm : null;
  const perOwner = new Map<number, number>();
  let total = 0;
  for (const stage of stages) {
    const duration = stageDuration(stage);
    total += duration;
    if (finite(stage.owner)) perOwner.set(stage.owner, (perOwner.get(stage.owner) ?? 0) + duration);
  }
  const singleOwnerFloor = Math.max(0, ...perOwner.values());
  if (!stages.length) {
    return { id: 'makespan-floor', label: 'Makespan covers declared compute', result: 'UNKNOWN', evidence: 'No compute stages in the draft.' };
  }
  if (aggregate === null) {
    return {
      id: 'makespan-floor', label: 'Makespan covers declared compute', result: 'UNKNOWN',
      evidence: `No SYSTEM_MAKESPAN recorded. Single-owner floor ${seconds(singleOwnerFloor)}; all-stage floor ${seconds(total)}.`,
    };
  }
  const evidence = `Makespan ${aggregate.toLocaleString()} cyc = compute ${singleOwnerFloor.toLocaleString()} + exposed ${exposed === null ? '—' : exposed.toLocaleString()} cyc`;
  if (aggregate < singleOwnerFloor) {
    return {
      id: 'makespan-floor', label: 'Makespan covers declared compute', result: 'FAIL',
      evidence,
      detail: `The reported makespan is below the largest per-owner compute duration (${seconds(singleOwnerFloor)}).`,
    };
  }
  if (placementDistributed && aggregate < total) {
    return {
      id: 'makespan-floor', label: 'Makespan covers declared compute', result: 'FAIL',
      evidence,
      detail: `The makespan is below the all-stage compute floor (${seconds(total)}). A single-owner stage model has parallelized layers across ranks; the number cannot be read as a sequential layer makespan.`,
    };
  }
  return {
    id: 'makespan-floor', label: 'Makespan covers declared compute', result: 'PASS',
    evidence,
  };
}

export function deriveTrustChecks(project: LoadedProject, run: LoadedRun): TrustCheck[] {
  const stages = stagesOf(project.request);
  const { tp, dp, ep, pp, ranks } = parallelism(project.request);
  const checks: TrustCheck[] = [];
  // A run may execute a recompiled system root when only certificate labels
  // changed; say so instead of letting the run look identity-matched.
  const parity = run.detail.compilation_parity ?? 'MATCHED';
  const shortHash = (value?: string | null) => value ? `${value.slice(0, 12)}…` : 'not recorded';
  checks.push({
    id: 'compilation-parity',
    label: 'Run matches the stored compilation',
    result: parity === 'MATCHED' ? 'PASS' : 'REVIEW',
    evidence: parity === 'MATCHED'
      ? 'Stored and recompiled artifact identities match.'
      : `${parity} · executed ${shortHash(run.detail.executed_compiled_system_hash)} instead of stored ${shortHash(run.detail.stored_compiled_system_hash)}.`,
    detail: parity === 'MATCHED' ? undefined
      : run.detail.compilation_parity_note
        ?? 'The design was recompiled; compare the recorded roots before treating this evidence as identical to the stored compilation.',
  });
  const draftMatches = !project.draftMeta?.dirty && project.detail.active_revision_id === run.detail.revision_id;
  checks.push({
    id: 'draft-revision',
    label: 'Draft matches the evaluated revision',
    result: draftMatches ? 'PASS' : 'REVIEW',
    evidence: draftMatches
      ? `revision ${run.detail.revision_id}`
      : `run ${run.detail.revision_id} · draft ${project.detail.active_revision_id ?? 'not compiled'}${project.draftMeta?.dirty ? ' · unsaved changes' : ''}`,
    detail: draftMatches ? undefined : 'Stage checks below read the current draft, not a captured copy of the evaluated request.',
  });
  const ids = stages.map(stage => String(stage.stage_id ?? '').trim());
  const duplicateIds = ids.filter((id, index) => id !== '' && ids.indexOf(id) !== index);
  checks.push({
    id: 'stage-identity',
    label: 'Stage identities are unique',
    result: stages.length === 0 ? 'UNKNOWN' : duplicateIds.length ? 'FAIL' : 'PASS',
    evidence: stages.length === 0 ? 'No compute stages declared.' : `${stages.length} stages${duplicateIds.length ? ` · duplicates: ${[...new Set(duplicateIds)].slice(0, 4).join(', ')}` : ' · no duplicate ids'}`,
  });

  const { layers, named } = numberedLayers(stages);
  if (!stages.length) {
    checks.push({ id: 'layer-coverage', label: 'Every declared layer has attention and MoE', result: 'UNKNOWN', evidence: 'No compute stages declared.' });
  } else if (!named || layers.size === 0) {
    checks.push({ id: 'layer-coverage', label: 'Every declared layer has attention and MoE', result: 'REVIEW', evidence: 'Stage ids do not use the layerN_attn / layerN_moe convention; coverage is not inferred.' });
  } else {
    const missing = [...layers.entries()].filter(([, kinds]) => !kinds.has('attn') || !kinds.has('moe')).map(([layer, kinds]) => `layer${layer} (${[...kinds].join(', ')})`);
    checks.push({
      id: 'layer-coverage',
      label: 'Every declared layer has attention and MoE',
      result: missing.length ? 'FAIL' : 'PASS',
      evidence: missing.length ? `${missing.length} incomplete layer${missing.length === 1 ? '' : 's'}: ${missing.slice(0, 4).join('; ')}` : `${layers.size} layers × 2 stages`,
    });
  }

  const owners = [...new Set(stages.map(stage => stage.owner).filter(finite))];
  const invalidOwners = owners.filter(owner => owner < 0 || owner >= ranks);
  checks.push({
    id: 'owner-range',
    label: 'Stage owners are valid ranks',
    result: !stages.length ? 'UNKNOWN' : invalidOwners.length ? 'FAIL' : owners.length ? 'PASS' : 'REVIEW',
    evidence: !stages.length ? 'No compute stages declared.' : `${owners.length} owner${owners.length === 1 ? '' : 's'} · declared ${ranks} rank${ranks === 1 ? '' : 's'}${invalidOwners.length ? ` · invalid: ${invalidOwners.join(', ')}` : ''}`,
  });

  const distributed = owners.length > 1 && stages.length > owners.length;
  const distributedParallelModel = distributed && pp === 1 && (tp * dp * ep) > 1;
  checks.push({
    id: 'placement-parallelism',
    label: 'Stage placement matches model parallelism',
    result: !stages.length || !owners.length ? 'UNKNOWN' : distributedParallelModel ? 'FAIL' : distributed ? 'REVIEW' : 'PASS',
    evidence: !stages.length ? 'No compute stages declared.' : `${stages.length} stages on ${owners.length} owners · tp ${tp} · dp ${dp} · ep ${ep} · pp ${pp}`,
    detail: distributedParallelModel
      ? 'A single owner per stage cannot represent a TP/EP-sharded layer. With pp=1, every layer must execute across its TP×EP rank group; the current owners spread different layers across ranks instead.'
      : distributed
        ? 'More than one owner is declared; confirm that the distribution is the intended pipeline or replica placement.'
        : 'One owner is declared for every stage.',
  });

  checks.push(makespanCheck(stages, run, distributedParallelModel));

  const network = analysisByQuestion(run, 'NETWORK_COMPLETION');
  const memory = analysisByQuestion(run, 'DRAM_TIMING');
  const topLevelCycles = run.detail.evaluation?.metrics?.completion_cycles;
  const networkCycles = metricValue(network, 'completion_cycles');
  const memoryCycles = metricValue(memory, 'completion_cycles');
  checks.push({
    id: 'metric-provenance',
    label: 'Top-level cycles resolve to one model',
    result: !finite(topLevelCycles) ? 'UNKNOWN' : networkCycles !== null && topLevelCycles === networkCycles ? 'PASS' : memoryCycles !== null && topLevelCycles === memoryCycles ? 'FAIL' : 'REVIEW',
    evidence: !finite(topLevelCycles)
      ? 'No top-level completion_cycles recorded.'
      : `top-level ${topLevelCycles.toLocaleString()} · network ${networkCycles === null ? '—' : networkCycles.toLocaleString()} · memory ${memoryCycles === null ? '—' : memoryCycles.toLocaleString()} cyc`,
    detail: finite(topLevelCycles) && memoryCycles !== null && topLevelCycles === memoryCycles
      ? 'The top-level completion metric is the memory completion metric, not the network completion metric.'
      : finite(topLevelCycles) && networkCycles !== null && topLevelCycles !== networkCycles
        ? 'The top-level completion metric does not match the network completion analysis. Check which analysis owns it before comparing runs.'
        : undefined,
  });

  const entries = run.detail.requirements?.entries ?? [];
  const missingAuthority = entries.filter(entry => !entry.metric_authority || !entry.performance_result_id);
  checks.push({
    id: 'requirement-authority',
    label: 'Requirement verdicts name their authority',
    result: !entries.length ? 'UNKNOWN' : missingAuthority.length ? 'REVIEW' : 'PASS',
    evidence: !entries.length ? 'No requirement verdicts recorded.' : `${entries.length} verdict${entries.length === 1 ? '' : 's'} · ${missingAuthority.length} without a full authority record`,
  });

  const analyses = run.detail.analyses ?? [];
  const incomplete = analyses.filter(analysis => analysis.status !== 'EVALUATED' || !analysis.model_fidelity || !analysis.qualification);
  checks.push({
    id: 'analysis-fidelity',
    label: 'Every analysis declares fidelity and qualification',
    result: !analyses.length ? 'UNKNOWN' : incomplete.length ? 'REVIEW' : 'PASS',
    evidence: !analyses.length ? 'No analyses recorded.' : `${analyses.length} analyses · ${incomplete.length} without a complete status/fidelity/qualification record`,
  });

  const bundle = Boolean(run.detail.bundle_id);
  const evidence = Boolean(run.detail.evidence?.evidence_id);
  checks.push({
    id: 'bundle-identity',
    label: 'Run, bundle and evidence identities are recorded',
    result: bundle && evidence ? 'PASS' : 'REVIEW',
    evidence: `run ${run.detail.run_id.slice(0, 12)}… · bundle ${bundle ? 'recorded' : 'missing'} · evidence ${evidence ? 'recorded' : 'missing'}`,
  });

  if (run.integrity) {
    const packet = run.integrity.packet_conservation;
    const flit = run.integrity.flit_conservation;
    const packetValues = Object.values(packet ?? {}).filter(entry => entry && typeof entry === 'object').map(entry => (entry as { value?: number | null }).value).filter((value): value is number => finite(value));
    const flitValues = Object.values(flit ?? {}).filter(entry => entry && typeof entry === 'object').map(entry => (entry as { value?: number | null }).value).filter((value): value is number => finite(value));
    const packetOk = packetValues.length > 0 && new Set(packetValues).size <= 1;
    const flitOk = flitValues.length > 0 && new Set(flitValues).size <= 1;
    checks.push({
      id: 'conservation',
      label: 'Backend-reported flow conservation agrees',
      result: packetOk && flitOk ? 'PASS' : (packetValues.length || flitValues.length) ? 'REVIEW' : 'UNKNOWN',
      evidence: `packet ${packetValues.length ? packetValues.join(' / ') : 'not recorded'} · flit ${flitValues.length ? flitValues.join(' / ') : 'not recorded'}`,
    });
  }

  return checks;
}

export function trustSummary(checks: TrustCheck[]): { pass: number; fail: number; review: number; unknown: number } {
  return checks.reduce((counts, check) => {
    if (check.result === 'PASS') counts.pass += 1;
    else if (check.result === 'FAIL') counts.fail += 1;
    else if (check.result === 'REVIEW') counts.review += 1;
    else counts.unknown += 1;
    return counts;
  }, { pass: 0, fail: 0, review: 0, unknown: 0 });
}
