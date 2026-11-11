export type InjectionRow = { line: number; cycle: number; source: number; destination: number; trafficClass: string; flits: number };

export type InjectionSpan = {
  total: number;
  firstCycle: number;
  lastCycle: number;
  flits: number;
  sources: number;
  destinations: number;
  dialect: 'CSV' | 'Whitespace';
};

export function isInjectionTraceArtifact(path: string): boolean {
  return /\.trace$/.test(path) && !path.includes('/ramulator/');
}

export function selectInjectionTrace(paths: readonly string[]): string | undefined {
  return paths.find(path => path.endsWith('/network_completion/run/workload.trace'))
    ?? paths.find(path => path.endsWith('/workload.trace') && isInjectionTraceArtifact(path))
    ?? paths.find(isInjectionTraceArtifact);
}

type InjectionFields = Omit<InjectionRow, 'line'>;

const integer = (value: string, line: number) => {
  const number = Number(value);
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(number)) throw new Error(`Line ${line}: invalid nonnegative integer.`);
  return number;
};

// BookSim's two input-trace dialects. These are requested injections, not observed hops.
function parseInjectionLine(line: string, index: number, csv: boolean): InjectionFields {
  const fields = csv ? line.split(',').map(s => s.trim()) : line.split(/\s+/);
  if (fields.length < 5) throw new Error(`Line ${index + 1}: expected five trace fields.`);
  const cycle = integer(fields[0], index + 1), source = integer(fields[1], index + 1);
  const destination = integer(fields[csv ? 2 : 3], index + 1), trafficClass = fields[csv ? 3 : 2];
  if (!trafficClass || (!csv && !/^\d+$/.test(trafficClass))) throw new Error(`Line ${index + 1}: invalid traffic class.`);
  const flits = integer(fields[4], index + 1); if (!flits) throw new Error(`Line ${index + 1}: packet size must be positive.`);
  return { cycle, source, destination, trafficClass, flits };
}

export function decodeInjectionTrace(text: string, maximumRows = 1000) {
  const rows: InjectionRow[] = []; let total = 0, csv: boolean | undefined;
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim(); if (!line || /^[#%]/.test(line)) continue;
    csv ??= line.includes(',');
    const fields = csv ? line.split(',').map(s => s.trim()) : line.split(/\s+/);
    if (csv && total === 0 && ['timestamp', 'cycle', 'time'].includes(fields[0].toLowerCase())) continue;
    const record = parseInjectionLine(line, index, csv);
    ++total; if (rows.length < maximumRows) rows.push({ line: index + 1, ...record });
  }
  if (!total) throw new Error('No injection records found.');
  return { rows, total, dialect: csv ? 'CSV' : 'Whitespace' } as const;
}

/** Only the endpoints of the requested-injection clock, for the run-level
 *  cycle budget. Full rows are unnecessary and cap at 20k elsewhere. */
export function scanInjectionTrace(text: string): InjectionSpan {
  let total = 0, flits = 0, firstCycle = Infinity, lastCycle = -Infinity;
  const sources = new Set<number>(), destinations = new Set<number>();
  let csv: boolean | undefined;
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim(); if (!line || /^[#%]/.test(line)) continue;
    csv ??= line.includes(',');
    const fields = csv ? line.split(',').map(s => s.trim()) : line.split(/\s+/);
    if (csv && total === 0 && ['timestamp', 'cycle', 'time'].includes(fields[0].toLowerCase())) continue;
    const record = parseInjectionLine(line, index, csv);
    total += 1;
    flits += record.flits;
    firstCycle = Math.min(firstCycle, record.cycle);
    lastCycle = Math.max(lastCycle, record.cycle);
    sources.add(record.source);
    destinations.add(record.destination);
  }
  if (!total) throw new Error('No injection records found.');
  return {
    total, firstCycle, lastCycle, flits,
    sources: sources.size, destinations: destinations.size,
    dialect: csv ? 'CSV' : 'Whitespace',
  };
}
