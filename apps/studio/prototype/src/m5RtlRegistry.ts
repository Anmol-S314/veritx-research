import type { M5RtlPrototype } from './gateway';

/** Unknown or unrecognized backend states remain explicitly unverified. */
export function evidenceState(value: unknown, unknownLabel = 'Unknown'): string {
  return typeof value === 'string' && value.trim() ? value : unknownLabel;
}

export function prototypeFileState(row: Pick<M5RtlPrototype, 'file_presence' | 'verilog_status'>): string {
  if (row.file_presence === 'PRESENT' && row.verilog_status === 'PRESENT') return 'Verilog present';
  if (row.file_presence === 'UNKNOWN') return 'Presence unknown';
  if (row.verilog_status === 'MISSING') return 'No Verilog file';
  return 'Unverified';
}

export function artifactSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Size unknown';
  return bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KiB` : `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
