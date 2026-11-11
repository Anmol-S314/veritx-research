import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  buildStudyConstraints,
  buildStudyObjectives,
  ClassScopedStudyResults,
  declaredTrafficClasses,
  metricSupportsTrafficClass,
  studyMetricOptions,
  TrafficClassSelect,
} from './LiveOperations';
import { AnalysisCell, catalogPerClassMetrics, metricDimensions } from './CatalogCampaign';

const classedCatalog = [
  { metric: 'system_makespan_cycles', question: 'SYSTEM_MAKESPAN', optimization_eligible: true, unit: 'cycles', dimensions: [] },
  { metric: 'flits_injected', question: 'NETWORK_COMPLETION', optimization_eligible: true, dimensions: ['traffic_class'] },
  { metric: 'pkt_count', question: 'NETWORK_COMPLETION', optimization_eligible: true, unit: 'packets', dimensions: ['traffic_class'] },
  { metric: 'flits_accepted', question: 'NETWORK_COMPLETION', optimization_eligible: false, dimensions: ['traffic_class'] },
  { metric: 'per_rank_flits', question: 'PER_RANK_COMPLETION', optimization_eligible: false, dimensions: ['rank'] },
];

describe('bounded study traffic-class selectors', () => {
  it('leaves the aggregate objective payload unchanged', () => {
    const objectives = buildStudyObjectives({ metric: 'completion_cycles', question: 'NETWORK_COMPLETION' });
    expect(objectives).toEqual([{ metric: 'completion_cycles', direction: 'MIN', question: 'NETWORK_COMPLETION' }]);
    expect(JSON.stringify(objectives)).not.toContain('traffic_class');

    const constraints = buildStudyConstraints([{ metric: 'completion_cycles', op: '<=', threshold: '5000' }]);
    expect(constraints).toEqual([{ metric: 'completion_cycles', op: '<=', threshold: 5000 }]);
    expect(JSON.stringify(constraints)).not.toContain('traffic_class');
  });

  it('offers the selector only for a metric the catalog declares as class-scoped', () => {
    const metrics = studyMetricOptions(classedCatalog);
    expect(metrics.map(metric => metric.metric)).toEqual(['completion_cycles', 'system_makespan_cycles', 'flits_injected', 'pkt_count']);
    expect(metricSupportsTrafficClass(metrics.find(metric => metric.metric === 'flits_injected'))).toBe(true);
    expect(metricSupportsTrafficClass(metrics.find(metric => metric.metric === 'completion_cycles'))).toBe(false);

    const html = renderToStaticMarkup(createElement(TrafficClassSelect, {
      label: 'Objective traffic class',
      value: 'tp_collective',
      classes: ['ep_dispatch', 'tp_collective'],
      onChange: () => undefined,
    }));
    expect(html).toContain('No class');
    expect(html).toContain('tp_collective');
    expect(html).toContain('ep_dispatch');
    expect(html).toContain('selected');
  });

  it('sends the selected class on both the objective and each constraint', () => {
    expect(buildStudyObjectives({
      metric: 'flits_injected', question: 'NETWORK_COMPLETION', trafficClass: 'tp_collective',
    })).toEqual([{
      metric: 'flits_injected', direction: 'MIN', question: 'NETWORK_COMPLETION', traffic_class: 'tp_collective',
    }]);
    expect(buildStudyConstraints([
      { metric: 'flits_injected', op: '<=', threshold: '10', traffic_class: 'tp_collective' },
      { metric: 'completion_cycles', op: '<=', threshold: '5000' },
    ])).toEqual([
      { metric: 'flits_injected', op: '<=', threshold: 10, traffic_class: 'tp_collective' },
      { metric: 'completion_cycles', op: '<=', threshold: 5000 },
    ]);
  });

  it('reads class choices only from declared workload classes, never from the metric catalog', () => {
    const classes = declaredTrafficClasses({
      request: {
        workload: { collectives: [{ traffic_class: 'tp_collective' }, { traffic_class: 'ep_dispatch' }] },
        requirements: [{ traffic_class: 'tp_collective' }, { traffic_class: 'bulk' }],
      },
      detail: { active_revision: { design: { requirements: [{ traffic_class: 'control' }] } } },
      compileResult: { groups: { resources: { traffic_class_to_vcs: [['latency_sensitive', [0, 1]]] } } },
    });
    expect(classes).toEqual(['bulk', 'control', 'ep_dispatch', 'latency_sensitive', 'tp_collective'].sort());
    expect(declaredTrafficClasses({ request: { workload: { collectives: [] } } })).toEqual([]);
    expect(declaredTrafficClasses({ request: { base_v4: { workload: { collectives: [{ traffic_class: 'v5_class' }] } } } })).toEqual(['v5_class']);
  });
});

describe('class-scoped study results', () => {
  const study = {
    // The top-level definition is the request echo and carries no axis keys.
    definition: { objectives: [{ metric: 'flits_injected', direction: 'MIN', question: 'NETWORK_COMPLETION', traffic_class: 'tp_collective' }] },
    study: {
      definition: {
        objectives: [{ metric: 'flits_injected', direction: 'MIN', question: 'NETWORK_COMPLETION', traffic_class: 'tp_collective', key: 'backend-owned-axis-1' }],
        constraints: [{ metric: 'flits_accepted', op: '<=', threshold: 10, traffic_class: 'ep_dispatch', key: 'backend-owned-axis-2' }],
      },
      candidates: [{
        candidate_id: 'c1',
        guided_patch: { link_width: 64 },
        objective_values: { 'backend-owned-axis-1': 123 },
        objective_availability: { 'backend-owned-axis-1': 'MEASURED' },
        constraint_verdicts: { 'backend-owned-axis-2': 'SATISFIED' },
        constraint_details: [{ metric: 'flits_accepted', traffic_class: 'ep_dispatch', measured: 8, required: 10 }],
      }],
    },
  };

  it('renders class-scoped values and verdicts from the backend axis keys', () => {
    const html = renderToStaticMarkup(createElement(ClassScopedStudyResults, { study }));
    expect(html).toContain('flits_injected · tp_collective');
    expect(html).toContain('123');
    expect(html).toContain('flits_accepted · ep_dispatch');
    expect(html).toContain('SATISFIED');
    expect(html).toContain('8 measured / 10 required');
    expect(html).not.toContain('backend-owned-axis-1');
    expect(html).not.toContain('@traffic_class=');
  });

  it('never shows an aggregate value under a class when the backend omitted the axis key', () => {
    const html = renderToStaticMarkup(createElement(ClassScopedStudyResults, { study: {
      study: {
        definition: { objectives: [{ metric: 'flits_injected', direction: 'MIN', traffic_class: 'tp_collective' }] },
        candidates: [{ candidate_id: 'c1', objective_values: { flits_injected: 999 }, objective_availability: { flits_injected: 'MEASURED' } }],
      },
    } }));
    expect(html).toContain('Not measured');
    expect(html).not.toContain('999');
  });

  it('renders nothing for an entirely aggregate study', () => {
    const aggregate = {
      definition: { objectives: [{ metric: 'completion_cycles', direction: 'MIN' }] },
      study: { definition: { objectives: [{ metric: 'completion_cycles', direction: 'MIN' }] }, candidates: [{ candidate_id: 'c1', objective_values: { completion_cycles: 10 } }] },
    };
    expect(renderToStaticMarkup(createElement(ClassScopedStudyResults, { study: aggregate }))).toBe('');
  });
});

describe('catalog per-class metrics', () => {
  it('groups traffic-class dimensions by class and keeps the aggregate row', () => {
    const analysis = {
      question: 'NETWORK_COMPLETION',
      backend_id: 'BOOKSIM_STANDALONE',
      status: 'EVALUATED',
      normalized_metrics: [
        { key: 'completion_cycles', value: 900, unit: 'cycles', dimensions: [] },
        { key: 'flits_injected', value: 10, unit: 'flits', dimensions: [['traffic_class', 'tp_collective']] },
        { key: 'packet_latency_avg', value: 42, unit: 'cycles', dimensions: [['traffic_class', 'tp_collective']] },
        { key: 'flits_injected', value: 3, unit: 'flits', dimensions: [['traffic_class', 'ep_dispatch']] },
        { key: 'flits_injected', value: 20, unit: 'flits', dimensions: [['traffic_class', 'tp_collective'], ['rank', '0']] },
        { key: 'flits_injected', value: 99, unit: 'flits', dimensions: [['rank', '0']] },
      ],
    };
    const groups = catalogPerClassMetrics(analysis as any);
    expect(groups.map(group => group.trafficClass)).toEqual(['tp_collective', 'ep_dispatch']);
    expect(groups[0].metrics.map(metric => metric.key)).toEqual(['flits_injected', 'packet_latency_avg']);
    expect(metricDimensions(groups[0].metrics[0])).toEqual([['traffic_class', 'tp_collective']]);

    const html = renderToStaticMarkup(createElement(AnalysisCell, { analysis: analysis as any }));
    expect(html).toContain('900');
    expect(html).toContain('Per traffic class');
    expect(html).toContain('tp_collective');
    expect(html).toContain('ep_dispatch');
    expect(html).toContain('packet latency avg');
    expect(html).not.toContain('rank');
    expect(html).not.toContain('99');
    const compact = renderToStaticMarkup(createElement(AnalysisCell, { analysis: analysis as any, compact: true }));
    expect(compact).toContain('900');
    expect(compact).not.toContain('Per traffic class');
    expect(compact).not.toContain('<details');
    expect(compact).not.toContain('tp_collective');
    expect(html).toContain('<table');
    expect(html).toContain('Unit</th>');
  });

  it('renders the aggregate exactly as before when no per-class evidence exists', () => {
    const analysis = {
      question: 'NETWORK_COMPLETION',
      backend_id: 'BOOKSIM_STANDALONE',
      status: 'EVALUATED',
      normalized_metrics: [{ key: 'completion_cycles', value: 900, unit: 'cycles', dimensions: [] }],
    };
    expect(catalogPerClassMetrics(analysis as any)).toEqual([]);
    const html = renderToStaticMarkup(createElement(AnalysisCell, { analysis: analysis as any }));
    expect(html).toContain('900');
    expect(html).not.toContain('Per traffic class');
  });
});
