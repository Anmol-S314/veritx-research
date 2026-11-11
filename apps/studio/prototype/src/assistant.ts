import { channelCosts, median, type LoadChannel } from './channelAnalysis';
import type { LoadedProject, LoadedRun } from './project';

/** A measured channel shaped for the assistant's small answer surface. */
export type AssistantChannel = {
  id: number;
  flits: number;
  utilization: number;
  peakWindow: number;
  queuePerFlit: number | null;
  tailRatio: number | null;
  meanHop: number | null;
  peakHop: number | null;
  queueCycles: number | null;
};

export type AssistantMeasured = {
  channels: number;
  active: number;
  totalFlits: number;
  topFlits: AssistantChannel | null;
  topCost: AssistantChannel | null;
  medianCost: number | null;
  medianFlits: number | null;
  band: number;
  topTenCost: AssistantChannel[];
  topTenFlits: AssistantChannel[];
  overlap: number;
  selected: AssistantChannel | null;
};

export type AssistantContext = {
  project: string | null;
  projectId: string | null;
  revision: string | null;
  run: string | null;
  runStatus: string | null;
  backend: string | null;
  qualification: string | null;
  page: string;
  pageTitle: string;
  group: string;
  selection: string | null;
  measured: AssistantMeasured | null;
  gaps: string[];
};

export type AssistantQuestion = 'overview' | 'cost' | 'selected' | 'volume' | 'overlap' | 'next' | 'missing' | 'page';

export type AssistantAction = { label: string; page?: string; channel?: string; scroll?: string };

export type AssistantAnswer = {
  paragraphs: string[];
  evidence: { label: string; value: string }[];
  actions: AssistantAction[];
  caveat?: string;
};

const number = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString();
const cyc = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)} cyc`;
const percent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : `${(100 * value).toFixed(1)} %`;

function line(cost: ReturnType<typeof channelCosts>[number]): AssistantChannel {
  const channel = cost.channel;
  return {
    id: cost.id,
    flits: channel.flits_total,
    utilization: channel.utilization,
    peakWindow: channel.peak_window_utilization,
    queuePerFlit: cost.queuePerFlit,
    tailRatio: cost.tailRatio,
    meanHop: channel.per_hop_latency_mean_cycles ?? null,
    peakHop: channel.peak_per_hop_latency_cycles ?? null,
    queueCycles: channel.queue_cycles_total ?? null,
  };
}

export function buildAssistantContext(args: {
  page: { id: string; title: string; group: string } | null;
  project: LoadedProject | null;
  run: LoadedRun | null;
  channels: LoadChannel[];
  selected: string;
  measuredPhase?: string;
  measuredReason?: string;
}): AssistantContext {
  const { page, project, run, channels, selected } = args;
  const costs = channelCosts(channels);
  const active = costs.map(line);
  const costed = active.filter((channel): channel is AssistantChannel & { queuePerFlit: number } => channel.queuePerFlit !== null);
  const byCost = [...costed].sort((a, b) => b.queuePerFlit - a.queuePerFlit);
  const byFlits = [...active].sort((a, b) => b.flits - a.flits);
  const band = Math.min(10, active.length);
  const topTenCost = byCost.slice(0, band);
  const topTenFlits = byFlits.slice(0, band);
  const topFlits = byFlits[0] ?? null;
  const topCost = byCost[0] ?? null;
  const selectedChannel = selected ? active.find(channel => String(channel.id) === selected) ?? null : null;
  const totalFlits = active.reduce((sum, channel) => sum + channel.flits, 0);
  const overlap = topTenCost.filter(channel => topTenFlits.some(other => other.id === channel.id)).length;
  const measured: AssistantMeasured | null = channels.length ? {
    channels: channels.length,
    active: active.length,
    totalFlits,
    topFlits,
    topCost,
    medianCost: median(costed.map(channel => channel.queuePerFlit)),
    medianFlits: median(active.map(channel => channel.flits)),
    band,
    topTenCost,
    topTenFlits,
    overlap,
    selected: selectedChannel,
  } : null;

  const gaps = new Set<string>();
  if (!project) gaps.add('No project is loaded.');
  if (!run) gaps.add('No run is selected.');
  if (channels.length === 0) gaps.add(args.measuredPhase === 'absent'
    ? 'This run has no sampled channel counters.'
    : args.measuredPhase === 'error'
      ? `The sampled channel counters could not be read: ${args.measuredReason ?? 'unknown reason'}.`
      : 'Sampled channel counters are not available yet.');
  if (active.length === 0) gaps.add('No measured channel carries a delivered flit.');
  if (!topCost) gaps.add('No channel carries a measured queue cost.');
  gaps.add('Per-packet latency percentiles, unique packets per channel, power, and area are not present in this run.');
  for (const limitation of run?.detail.analyses?.flatMap(analysis => analysis.limitations ?? []) ?? []) gaps.add(limitation);

  return {
    project: project?.detail.project.name ?? null,
    projectId: project?.detail.project.project_id ?? null,
    revision: project?.detail.active_revision_id ?? null,
    run: run?.detail.run_id ?? null,
    runStatus: run?.detail.status ?? null,
    backend: run?.detail.backend ?? null,
    qualification: run?.detail.qualification ?? null,
    page: page?.id ?? 'unknown',
    pageTitle: page?.title ?? 'Unknown view',
    group: page?.group ?? 'Unknown',
    selection: selectedChannel ? `CH-${selectedChannel.id}` : selected ? `CH-${selected}` : null,
    measured,
    gaps: [...gaps].slice(0, 8),
  };
}

export function suggestedQuestions(context: AssistantContext): { id: AssistantQuestion; label: string }[] {
  if (!context.measured) {
    return [
      { id: 'page', label: 'What does this page show?' },
      { id: 'next', label: 'What should I inspect next?' },
      { id: 'missing', label: 'What is missing from this evidence?' },
    ];
  }
  const measured = context.measured;
  const questions: { id: AssistantQuestion; label: string }[] = [
    { id: 'overview', label: 'What stands out in this run?' },
  ];
  if (measured.topCost) questions.push({ id: 'cost', label: `Why is CH-${measured.topCost.id} the costliest?` });
  if (measured.selected && measured.selected.queuePerFlit !== null && measured.selected.id !== measured.topCost?.id) {
    questions.push({ id: 'selected', label: `Why is CH-${measured.selected.id} expensive?` });
  }
  if (measured.overlap > 0) questions.push({ id: 'overlap', label: 'Which channels are both busy and expensive?' });
  if (measured.topFlits) questions.push({ id: 'volume', label: 'Which channel is the busiest?' });
  questions.push({ id: 'next', label: 'What should I inspect next?' }, { id: 'missing', label: 'What is missing from this evidence?' });
  return questions.slice(0, 5);
}

const PAGE_SUMMARY: Record<string, string> = {
  'analysis/topology': 'This page combines per-router load, fabric activity over windows, measured delay cost, projected playback, route attribution, and the declared channel list. Measured counters and derived attributions are labelled separately.',
  'analysis/summary': 'This page reads the selected run: requirement verdicts, reported metrics, analyses, and gaps. It does not evaluate the working draft.',
  'analysis/metrics': 'This page lists the run’s reported metrics and their declared scope. It does not infer distributions or physical implementation.',
  'analysis/trace': 'This page separates requested trace injections, observed-hop capture, and packet-latency evidence. A projection is not an observed trace.',
  'analysis/comparison': 'This page compares two runs through the backend compatibility gate. It does not guess statistical significance.',
  'analysis/matrix': 'This page reads endpoint-pair traffic from the run. It does not infer observed packet paths.',
  'design/system': 'This page shows declared agents, endpoint attachments, and fabric counts. It does not claim placement, timing, or traffic.',
  'workloads/workflow': 'This page edits working workload and requirement intent. Declared inputs are not measured results until a backend run exists.',
};

function selectedOrTop(context: AssistantContext, useSelected: boolean): AssistantChannel | null {
  if (useSelected && context.measured?.selected) return context.measured.selected;
  return context.measured?.topCost ?? context.measured?.topFlits ?? null;
}

export function answerQuestion(question: AssistantQuestion, context: AssistantContext): AssistantAnswer {
  const measured = context.measured;
  const cost = measured?.topCost ?? null;
  const flits = measured?.topFlits ?? null;
  const ratio = cost && measured?.medianCost ? cost.queuePerFlit !== null ? cost.queuePerFlit / measured.medianCost : null : null;

  if (question === 'page') {
    return {
      paragraphs: [
        PAGE_SUMMARY[context.page] ?? `${context.pageTitle} is part of the ${context.group} workspace. The assistant reads only the current project, run, page, and selection.`,
        context.run ? `The current context is ${context.project ?? 'no project'} · ${context.revision ?? 'no revision'} · run ${context.run.slice(0, 13)}${context.backend ? ` · ${context.backend}` : ''}.` : 'No live run is selected, so no measured evidence is attached.',
      ],
      evidence: [
        { label: 'Page', value: context.pageTitle },
        ...(context.run ? [{ label: 'Run', value: `${context.run.slice(0, 13)}…` }] : []),
        ...(context.qualification ? [{ label: 'Qualification', value: context.qualification }] : []),
      ],
      actions: [{ label: 'Open analysis summary', page: 'analysis/summary' }, { label: 'Inspect evidence', page: 'verify/evidence' }],
    };
  }

  if (question === 'missing') {
    return {
      paragraphs: [
        context.gaps.length ? 'This context does not establish the following:' : 'No explicit gaps were recorded in this context.',
        ...context.gaps.map(gap => `• ${gap}`),
        'A missing value is unavailable, not zero and not a pass.',
      ],
      evidence: [
        { label: 'Run', value: context.run ? `${context.run.slice(0, 13)}…` : 'not selected' },
        { label: 'Qualification', value: context.qualification ?? 'not declared' },
      ],
      actions: [{ label: 'Inspect evidence bundle', page: 'verify/evidence' }, { label: 'Review metric definitions', page: 'analysis/metrics' }],
      caveat: 'Nothing is filled by inference.',
    };
  }

  if (question === 'next') {
    if (cost) {
      return {
        paragraphs: [
          `Start with CH-${cost.id}: it is the costliest measured channel at ${cyc(cost.queuePerFlit)} per delivered flit${ratio === null ? '' : `, ${ratio.toFixed(1)}× the fabric median`}.`,
          `Then compare this run with the previous run on the same revision. If the cost persists, inspect the queue/arbitration split and the peak window before requesting a new evaluation.`,
        ],
        evidence: [
          { label: 'Costliest', value: `CH-${cost.id}` },
          { label: 'Queue / flit', value: cyc(cost.queuePerFlit) },
          ...(cost.tailRatio !== null ? [{ label: 'Tail', value: `${cost.tailRatio.toFixed(1)}×` }] : []),
        ],
        actions: [{ label: `Open CH-${cost.id}`, page: 'analysis/topology', channel: String(cost.id) }, { label: 'Compare runs', page: 'analysis/comparison' }, { label: 'Open delay cost', page: 'analysis/topology', scroll: 'measured-delay-cost' }],
        caveat: 'No evaluation is launched from here. A new run is a separate, explicit action.',
      };
    }
    return {
      paragraphs: [
        'No measured channel cost is available in this context. Start with the analysis summary and the run’s evidence bundle; the assistant cannot infer a bottleneck from endpoint-pair counts alone.',
      ],
      evidence: [{ label: 'Page', value: context.pageTitle }],
      actions: [{ label: 'Open analysis summary', page: 'analysis/summary' }, { label: 'Inspect evidence', page: 'verify/evidence' }],
    };
  }

  if (!measured) {
    return {
      paragraphs: [
        'This context has no sampled channel counters, so it cannot summarize channel activity, utilization, or per-flit cost.',
        context.run ? `The selected run is ${context.run.slice(0, 13)}…; open its summary or evidence to see what was actually recorded.` : 'Select a run to attach its measured evidence.',
      ],
      evidence: [
        { label: 'Run', value: context.run ? `${context.run.slice(0, 13)}…` : 'not selected' },
        { label: 'Backend', value: context.backend ?? 'not declared' },
      ],
      actions: [{ label: 'Open analysis summary', page: 'analysis/summary' }, { label: 'Inspect evidence', page: 'verify/evidence' }],
      caveat: 'No counter is invented to fill the gap.',
    };
  }

  if (question === 'overview') {
    return {
      paragraphs: [
        `${measured.active} of ${measured.channels} measured channels are active. The busiest is CH-${flits?.id ?? '—'} with ${number(flits?.flits)} flits${flits ? ` (${percent(flits.utilization)} sustained)` : ''}.`,
        `The costliest is CH-${cost?.id ?? '—'} at ${cyc(cost?.queuePerFlit)} per delivered flit${ratio === null ? '' : `, ${ratio.toFixed(1)}× the fabric median of ${cyc(measured.medianCost)}`}. ${measured.overlap} of the ${measured.band} costliest channels are also among the ${measured.band} busiest.`,
      ],
      evidence: [
        { label: 'Active', value: `${measured.active} / ${measured.channels}` },
        { label: 'Top flits', value: flits ? `CH-${flits.id} · ${number(flits.flits)}` : '—' },
        { label: 'Median cost', value: cyc(measured.medianCost) },
        { label: 'Cost ∩ volume', value: `${measured.overlap} / ${measured.band}` },
      ],
      actions: [
        ...(cost ? [{ label: `Open CH-${cost.id}`, page: 'analysis/topology', channel: String(cost.id) }] : []),
        { label: 'Open delay cost', page: 'analysis/topology', scroll: 'measured-delay-cost' },
        { label: 'Compare runs', page: 'analysis/comparison' },
      ],
      caveat: 'The per-flit cost is derived from measured queue counters; it is not a packet-latency percentile.',
    };
  }

  if (question === 'cost' || question === 'selected') {
    const target = question === 'selected' ? selectedOrTop(context, true) : cost;
    if (!target || target.queuePerFlit === null) {
      return {
        paragraphs: ['No channel in this context carries both a measured queue counter and a delivered flit.'],
        evidence: [{ label: 'Run', value: context.run ? `${context.run.slice(0, 13)}…` : 'not selected' }],
        actions: [{ label: 'Open delay cost', page: 'analysis/topology', scroll: 'measured-delay-cost' }],
        caveat: 'No cost is invented from endpoint-pair counts.',
      };
    }
    const targetRatio = measured.medianCost ? target.queuePerFlit / measured.medianCost : null;
    return {
      paragraphs: [
        `CH-${target.id} is ${question === 'cost' ? 'the costliest measured channel' : 'the selected channel'} at ${cyc(target.queuePerFlit)} per delivered flit${targetRatio === null ? '' : `, ${targetRatio.toFixed(1)}× the fabric median of ${cyc(measured.medianCost)}`}. It carried ${number(target.flits)} flits.`,
        target.tailRatio !== null ? `Its peak per-hop latency is ${target.tailRatio.toFixed(1)}× its mean, so one short burst sets the maximum rather than every flit waiting that long.` : 'Its peak-to-mean latency tail is not available in this context.',
      ],
      evidence: [
        { label: 'Channel', value: `CH-${target.id}` },
        { label: 'Queue / flit', value: cyc(target.queuePerFlit) },
        { label: 'Flits', value: number(target.flits) },
        ...(target.tailRatio !== null ? [{ label: 'Tail', value: `${target.tailRatio.toFixed(1)}×` }] : []),
      ],
      actions: [
        { label: `Open CH-${target.id}`, page: 'analysis/topology', channel: String(target.id) },
        { label: 'Show in delay scatter', page: 'analysis/topology', scroll: 'measured-delay-cost' },
        { label: 'Open traffic matrix', page: 'analysis/matrix' },
      ],
      caveat: 'High per-flit cost on one port is not a congestion verdict by itself. Check the queue/arbitration split and whether the peak is one window.',
    };
  }

  if (question === 'volume') {
    return {
      paragraphs: [
        `The busiest measured channel is CH-${flits?.id ?? '—'} with ${number(flits?.flits)} flits, ${percent(flits?.utilization)} sustained and ${percent(flits?.peakWindow)} in its peak window.`,
        `This is a source-port count, not a unique-packet count or a per-initiator total.`,
      ],
      evidence: [
        { label: 'Channel', value: flits ? `CH-${flits.id}` : '—' },
        { label: 'Flits', value: number(flits?.flits) },
        { label: 'Sustained', value: percent(flits?.utilization) },
        { label: 'Peak window', value: percent(flits?.peakWindow) },
      ],
      actions: flits ? [{ label: `Open CH-${flits.id}`, page: 'analysis/topology', channel: String(flits.id) }, { label: 'Open delay cost', page: 'analysis/topology', scroll: 'measured-delay-cost' }] : [],
      caveat: 'Busiest volume is not the same as highest per-flit cost.',
    };
  }

  if (question === 'overlap') {
    const ids = measured.topTenCost.filter(channel => measured.topTenFlits.some(other => other.id === channel.id));
    return {
      paragraphs: [
        ids.length
          ? `${ids.length} of the ${measured.band} costliest channels are also among the ${measured.band} busiest: ${ids.map(channel => `CH-${channel.id}`).join(', ')}.`
          : `The ${measured.band} costliest and ${measured.band} busiest channels are disjoint in this run. High per-flit cost on a low-volume port is not a congestion verdict by itself.`,
        'Use both axes before calling a link congested; overlap identifies where to look first, not a causal bottleneck.',
      ],
      evidence: [
        { label: 'Overlap', value: `${ids.length} / ${measured.band}` },
        ...(ids.length ? [{ label: 'Channels', value: ids.map(channel => `CH-${channel.id}`).join(', ') }] : []),
      ],
      actions: [{ label: 'Open delay cost', page: 'analysis/topology', scroll: 'measured-delay-cost' }, ...(ids[0] ? [{ label: `Open CH-${ids[0].id}`, page: 'analysis/topology', channel: String(ids[0].id) }] : [])],
      caveat: 'Overlap is a ranking comparison, not a shared-bottleneck proof.',
    };
  }

  return answerQuestion('overview', context);
}

export function answerFreeText(text: string, context: AssistantContext): AssistantAnswer {
  const lower = text.toLowerCase();
  if (/\b(cost|expensive|queue|delay)\b/.test(lower)) return answerQuestion('cost', context);
  if (/\b(busy|busiest|volume|flits)\b/.test(lower)) return answerQuestion('volume', context);
  if (/\b(overlap|both|busy and expensive)\b/.test(lower)) return answerQuestion('overlap', context);
  if (/\b(missing|gap|absent|not recorded|limitation)\b/.test(lower)) return answerQuestion('missing', context);
  if (/\b(next|inspect|look|check|recommend)\b/.test(lower)) return answerQuestion('next', context);
  if (/\b(page|view|show|what is this)\b/.test(lower)) return answerQuestion('page', context);
  return answerQuestion('overview', context);
}
