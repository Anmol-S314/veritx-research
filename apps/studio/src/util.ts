export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function getPath(obj: unknown, path: string): unknown {
  let node: unknown = obj;
  for (const seg of path.split('.')) {
    if (node === null || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[seg];
  }
  return node;
}

export function setPath(
  obj: Record<string, unknown>,
  path: string,
  value: unknown,
): void {
  const segs = path.split('.');
  let node: Record<string, unknown> = obj;
  for (const seg of segs.slice(0, -1)) {
    const next = node[seg];
    if (next === null || typeof next !== 'object') return;
    node = next as Record<string, unknown>;
  }
  node[segs[segs.length - 1]] = value;
}

export function asNumber(value: unknown): number | '' {
  return typeof value === 'number' ? value : '';
}
