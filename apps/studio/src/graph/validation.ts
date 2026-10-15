export type ValidationSeverity = 'error' | 'warning' | 'info';

/** Canonical structured finding used by the M0 project/workload/trace
 *  validators. It shares the editor's canonical `ProjectIssue` shape: a
 *  severity, a stable machine code, a human message, and a string reference to
 *  the object at fault (a JSON pointer or `$.nodes[id=x]` form). Keeping one
 *  shape means a caller can render any validator's output without
 *  special-casing which one produced it. */
export interface ValidationIssue {
  path: string;
  message: string;
  severity: ValidationSeverity;
  code: string;
  objectRef: string;
  components?: string[][];
  quickFix?: { label: string; code: string };
}

export function validationIssue(code: string, path: string, message: string, severity: ValidationSeverity = 'error'): ValidationIssue {
  return { path, message, severity, code, objectRef: path };
}
