export type ValidationSeverity = 'error' | 'warning' | 'info';

/** Canonical structured finding used by M0 project/workload/trace validators. */
export interface ValidationIssue {
  severity: ValidationSeverity;
  code: string;
  message: string;
  objectRef: { path: string; kind?: string; id?: string };
  quickFix?: { action: string; safe: true };
}

export function validationIssue(code: string, path: string, message: string, severity: ValidationSeverity = 'error'): ValidationIssue {
  return { severity, code, message, objectRef: { path } };
}
