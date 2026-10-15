import { PROVENANCE_STATES, type ProvenanceState } from './provenance';
import { validationIssue, type ValidationIssue } from './validation';

export interface RunSummaryMetricV1 {
  name: string;
  value: number | null;
  unit: string | null;
  provenance: ProvenanceState;
  unsupported: boolean;
  estimated: boolean;
}
export interface RunSummaryV1 {
  schemaVersion: 1;
  runId: string;
  backend: { id: string; version: string | null; provenance: ProvenanceState };
  metrics: RunSummaryMetricV1[];
  warnings: { code: string; severity: 'info' | 'warning' | 'error'; message: string }[];
}

const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;

/** Validate summary.json v1 while refusing invented numeric unsupported results. */
export function validateRunSummary(value: unknown): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const issue = (path: string, message: string): void => { issues.push(validationIssue('LOOM_SUMMARY_INVALID', path, message)); };
  if (!isRecord(value)) return [validationIssue('LOOM_SUMMARY_INVALID', '$', 'must be an object')];
  const allowed = ['schemaVersion', 'runId', 'backend', 'metrics', 'warnings'];
  for (const key of Object.keys(value)) if (!allowed.includes(key)) issue(`$.${key}`, 'unknown field');
  if (value.schemaVersion !== 1) issue('$.schemaVersion', 'must equal 1');
  if (!nonEmpty(value.runId)) issue('$.runId', 'must be a non-empty string');
  if (!isRecord(value.backend)) issue('$.backend', 'must be an object');
  else {
    for (const key of Object.keys(value.backend)) if (!['id', 'version', 'provenance'].includes(key)) issue(`$.backend.${key}`, 'unknown field');
    if (!nonEmpty(value.backend.id)) issue('$.backend.id', 'must be a non-empty string');
    if (value.backend.version !== null && typeof value.backend.version !== 'string') issue('$.backend.version', 'must be a string or null');
    if (!PROVENANCE_STATES.includes(value.backend.provenance as ProvenanceState)) issue('$.backend.provenance', 'must be a supported provenance state');
  }
  if (!Array.isArray(value.metrics)) issue('$.metrics', 'must be an array');
  else value.metrics.forEach((metric, index) => {
    const path = `$.metrics[${index}]`;
    if (!isRecord(metric)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(metric)) if (!['name', 'value', 'unit', 'provenance', 'unsupported', 'estimated'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    if (!nonEmpty(metric.name)) issue(`${path}.name`, 'must be a non-empty string');
    if (metric.value !== null && (typeof metric.value !== 'number' || !Number.isFinite(metric.value))) issue(`${path}.value`, 'must be a finite number or null');
    if (metric.unit !== null && typeof metric.unit !== 'string') issue(`${path}.unit`, 'must be a string or null');
    if (!PROVENANCE_STATES.includes(metric.provenance as ProvenanceState)) issue(`${path}.provenance`, 'must be a supported provenance state');
    if (typeof metric.unsupported !== 'boolean') issue(`${path}.unsupported`, 'must be boolean');
    if (typeof metric.estimated !== 'boolean') issue(`${path}.estimated`, 'must be boolean');
    if (metric.unsupported === true && metric.value !== null) issue(`${path}.value`, 'unsupported metric values must be null');
    if (metric.estimated === true && metric.provenance !== 'estimated') issue(`${path}.provenance`, 'estimated metrics must use estimated provenance');
  });
  if (!Array.isArray(value.warnings)) issue('$.warnings', 'must be an array');
  else value.warnings.forEach((warning, index) => {
    const path = `$.warnings[${index}]`;
    if (!isRecord(warning)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(warning)) if (!['code', 'severity', 'message'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    if (!nonEmpty(warning.code)) issue(`${path}.code`, 'must be a non-empty string');
    if (!['info', 'warning', 'error'].includes(String(warning.severity))) issue(`${path}.severity`, 'must be info, warning, or error');
    if (!nonEmpty(warning.message)) issue(`${path}.message`, 'must be a non-empty string');
  });
  return issues;
}
