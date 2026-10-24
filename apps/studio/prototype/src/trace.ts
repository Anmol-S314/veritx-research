export type InjectionRow = { line: number; cycle: number; source: number; destination: number; trafficClass: string; flits: number };
// BookSim's two input-trace dialects. These are requested injections, not observed hops.
export function decodeInjectionTrace(text: string, maximumRows = 1000) {
  const rows: InjectionRow[] = []; let total = 0, csv: boolean | undefined;
  const integer = (value: string, line: number) => {
    const number = Number(value);
    if (!/^\d+$/.test(value) || !Number.isSafeInteger(number)) throw new Error(`Line ${line}: invalid nonnegative integer.`);
    return number;
  };
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim(); if (!line || /^[#%]/.test(line)) continue;
    csv ??= line.includes(',');
    const fields = csv ? line.split(',').map(s => s.trim()) : line.split(/\s+/);
    if (csv && total === 0 && ['timestamp', 'cycle', 'time'].includes(fields[0].toLowerCase())) continue;
    if (fields.length < 5) throw new Error(`Line ${index + 1}: expected five trace fields.`);
    const cycle = integer(fields[0], index + 1), source = integer(fields[1], index + 1);
    const destination = integer(fields[csv ? 2 : 3], index + 1), trafficClass = fields[csv ? 3 : 2];
    if (!trafficClass || (!csv && !/^\d+$/.test(trafficClass))) throw new Error(`Line ${index + 1}: invalid traffic class.`);
    const flits = integer(fields[4], index + 1); if (!flits) throw new Error(`Line ${index + 1}: packet size must be positive.`);
    ++total; if (rows.length < maximumRows) rows.push({ line: index + 1, cycle, source, destination, trafficClass, flits });
  }
  if (!total) throw new Error('No injection records found.');
  return { rows, total, dialect: csv ? 'CSV' : 'Whitespace' };
}

export type RoutingRow = { line: number; srcRouter: number; dstNode: number; nextRouter: number; port: number };
// Executed first-hop realization table (routing.dump): one row per
// (source router, destination node) naming the next hop and egress port.
// It proves the first hop that was realized, never a full packet path.
export function decodeRoutingDump(text: string, maximumRows = 1000) {
  const rows: RoutingRow[] = []; let total = 0;
  const integer = (value: string, line: number) => {
    const number = Number(value);
    if (!/^\d+$/.test(value) || !Number.isSafeInteger(number)) throw new Error(`Line ${line}: invalid nonnegative integer.`);
    return number;
  };
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim(); if (!line || line.startsWith('#')) continue;
    const fields = line.split(/\s+/);
    if (fields.length !== 8 || fields[0] !== 'src_router' || fields[2] !== 'dst_node' || fields[4] !== 'next_router' || fields[6] !== 'port') throw new Error(`Line ${index + 1}: expected 'src_router <i> dst_node <j> next_router <k> port <p>'.`);
    ++total;
    if (rows.length < maximumRows) rows.push({ line: index + 1, srcRouter: integer(fields[1], index + 1), dstNode: integer(fields[3], index + 1), nextRouter: integer(fields[5], index + 1), port: integer(fields[7], index + 1) });
  }
  if (!total) throw new Error('No routing records found.');
  return { rows, total };
}
