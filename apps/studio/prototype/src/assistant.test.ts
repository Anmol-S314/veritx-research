import { describe, expect, it } from 'vitest';
import { answerFreeText, answerQuestion, buildAssistantContext, suggestedQuestions } from './assistant';
import type { LoadChannel } from './channelAnalysis';

const channels: LoadChannel[] = [
  { logical_channel_id: 0, flits_total: 1608, cycles_sampled: 1000, utilization: 0.594, peak_window_utilization: 0.8, queue_cycles_total: 9616, per_hop_latency_mean_cycles: 5.98, peak_per_hop_latency_cycles: 8 },
  { logical_channel_id: 10000, flits_total: 648, cycles_sampled: 1000, utilization: 0.174, peak_window_utilization: 0.9, queue_cycles_total: 6668, per_hop_latency_mean_cycles: 10.29, peak_per_hop_latency_cycles: 41 },
  { logical_channel_id: 4, flits_total: 0, cycles_sampled: 1000, utilization: 0, peak_window_utilization: 0 },
];

const page = { id: 'analysis/topology', title: 'Topology & Simulation Overlay', group: 'Analysis' };

describe('assistant context', () => {
  it('summarizes active channels and cost concentration from measured counters', () => {
    const context = buildAssistantContext({ page, project: null, run: null, channels, selected: '10000' });
    expect(context.measured?.active).toBe(2);
    expect(context.measured?.channels).toBe(3);
    expect(context.measured?.topFlits?.id).toBe(0);
    expect(context.measured?.topCost?.id).toBe(10000);
    expect(context.measured?.selected?.id).toBe(10000);
    expect(context.selection).toBe('CH-10000');
    expect(context.gaps.join(' ')).toContain('Per-packet latency');
  });

  it('answers the cost question with the selected channel and a caveat', () => {
    const context = buildAssistantContext({ page, project: null, run: null, channels, selected: '10000' });
    const answer = answerQuestion('cost', context);
    expect(answer.paragraphs.join(' ')).toContain('CH-10000');
    expect(answer.evidence).toEqual(expect.arrayContaining([{ label: 'Channel', value: 'CH-10000' }]));
    expect(answer.caveat).toContain('not a congestion verdict');
  });

  it('suggests page-specific questions and never invents a cost when counters are absent', () => {
    const context = buildAssistantContext({ page, project: null, run: null, channels: [], selected: '' });
    expect(context.measured).toBeNull();
    expect(suggestedQuestions(context).map(question => question.id)).toEqual(['page', 'next', 'missing']);
    expect(answerQuestion('cost', context).paragraphs.join(' ')).toContain('no sampled channel counters');
    expect(answerFreeText('what is missing?', context).paragraphs.join(' ')).toContain('does not establish');
  });
});
