/** Bound visualization density without dropping samples. Sum counts; preserve maxima for peak lanes.
 *  `stride` overrides the automatic limit when the caller wants an explicit
 *  bucket size (for example one original window per column). */
export function bucketWindows(values: number[], limit = 80, mode: 'sum' | 'max' = 'sum', stride?: number) {
  const resolved = stride && Number.isFinite(stride) && stride > 0 ? Math.floor(stride) : Math.max(1, Math.ceil(values.length / limit));
  const buckets: number[] = [];
  for (let start = 0; start < values.length; start += resolved) {
    const slice = values.slice(start, start + resolved);
    buckets.push(mode === 'max' ? Math.max(...slice) : slice.reduce((a, b) => a + b, 0));
  }
  return { values: buckets, stride: resolved };
}
