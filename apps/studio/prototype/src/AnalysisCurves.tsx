import type { ReactElement } from 'react';
import { WorkloadPowerAnalysis } from './WorkloadPowerAnalysis';
import { Notice, PageLink } from './ui';
import type { LoadedProject } from './project';
import './analysisCharts.css';

/** The reference fixtures are a fixed set. Pick the one that matches the
 *  loaded revision's model family so a Qwen3 project does not open on the
 *  generic LLM-transformer trace. */
const REFERENCE_BY_MODEL: [RegExp, string][] = [
  [/qwen3.*(moe|mixture)|mixture.*qwen3/, 'qwen3-moe'],
  [/mixtral/, 'mixtral-8x7b-64tiles'],
  [/llama/, 'llama-3.1-8b-64tiles'],
  [/astr/, 'astr-llm-70b-tp4'],
  [/mwa|correlator/, 'mwa-fx-correlator'],
  [/recommend/, 'recommendation_system'],
  [/rnn|lstm/, 'rnn_lstm'],
  [/vision|vit/, 'vision_transformer'],
  [/transformer/, 'llm_transformer'],
  [/moe|mixture/, 'moe'],
];

const referenceWorkloadFor = (modelName?: string, modelFamily?: string): string | undefined =>
  REFERENCE_BY_MODEL.find(([pattern]) => pattern.test(`${modelName ?? ''} ${modelFamily ?? ''}`.toLowerCase()))?.[1];

/** Curves & Pareto keeps the repository workload reference. A project's
 *  measured study is analysed in Explore -> Revision study, beside the job
 *  and adoption that own it. */
export default function AnalysisCurves({ project }: { project?: LoadedProject }): ReactElement {
  const study = project?.detail.latest_optimization_study ?? project?.detail.optimizations?.[0] ?? null;
  const design = project?.detail.active_revision?.design as { workload?: { model_name?: string; model_family?: string; parallelism?: { tp?: number } } } | undefined;
  const requestWorkload = project?.request?.workload;
  const workload = design?.workload ?? requestWorkload;
  const tp = design?.workload?.parallelism?.tp ?? requestWorkload?.tp;
  const projectWorkload = workload
    ? `${workload.model_name || workload.model_family || 'unnamed'}${tp && tp > 1 ? ` · TP${tp}` : ''}`
    : undefined;
  const referenceWorkload = referenceWorkloadFor(workload?.model_name, workload?.model_family);
  return <>
    {project && (study
      ? <div className="curves-workspace"><Notice tone="blue"><strong>Repository workload reference.</strong> Project study results are in Explore → Revision study. <PageLink page="explore/brief">Open revision study</PageLink></Notice></div>
      : <div className="curves-workspace"><Notice tone="amber"><strong>This project has no measured optimization study.</strong> Run a bounded study in Explore to produce project-specific results. <PageLink page="explore/brief">Open bounded study</PageLink></Notice></div>)}
    <WorkloadPowerAnalysis projectWorkload={projectWorkload} initialWorkload={referenceWorkload} />
  </>;
}
