
export type Edge = [number, number];

export function canonEdge(u: number, v: number): Edge {
  return u < v ? [u, v] : [v, u];
}

export function edgeKey(e: Edge): string {
  return `${e[0]}-${e[1]}`;
}

export function parseLinks(text: string): { links: Edge[]; errors: string[] } {
  const links: Edge[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();
  text.split('\n').forEach((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith('#')) return;
    const m = line.match(/^(\d+)\s*[-,v\s]\s*(\d+)$/);
    if (!m) {
      errors.push(`line ${i + 1}: not a u-v pair: ${line}`);
      return;
    }
    const e = canonEdge(Number(m[1]), Number(m[2]));
    if (e[0] === e[1]) {
      errors.push(`line ${i + 1}: self-loop ${line}`);
      return;
    }
    const k = edgeKey(e);
    if (seen.has(k)) {
      errors.push(`line ${i + 1}: duplicate link ${line}`);
      return;
    }
    seen.add(k);
    links.push(e);
  });
  links.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return { links, errors };
}

export function serializeLinks(links: Edge[]): string {
  return links.map((e) => `${e[0]}-${e[1]}`).join('\n');
}

export function meshLinks(k: number): Edge[] {
  const out: Edge[] = [];
  for (let r = 0; r < k; r++) {
    for (let c = 0; c < k; c++) {
      const u = r * k + c;
      if (c + 1 < k) out.push(canonEdge(u, u + 1));
      if (r + 1 < k) out.push(canonEdge(u, u + k));
    }
  }
  return out;
}

export function degreeOf(nodes: number, links: Edge[]): number[] {
  const deg = new Array<number>(nodes).fill(0);
  for (const [u, v] of links) {
    if (u < nodes) deg[u] += 1;
    if (v < nodes) deg[v] += 1;
  }
  return deg;
}

export function maxNode(links: Edge[]): number {
  let m = -1;
  for (const [u, v] of links) m = Math.max(m, u, v);
  return m;
}

export function isConnected(nodes: number, links: Edge[]): boolean {
  if (nodes <= 1) return true;
  const adj: Set<number>[] = Array.from({ length: nodes }, () => new Set());
  for (const [u, v] of links) {
    if (u >= nodes || v >= nodes) return false;
    adj[u].add(v);
    adj[v].add(u);
  }
  const seen = new Set<number>([0]);
  const q = [0];
  while (q.length > 0) {
    const u = q.pop() as number;
    for (const v of adj[u]) {
      if (!seen.has(v)) {
        seen.add(v);
        q.push(v);
      }
    }
  }
  return seen.size === nodes;
}

export interface GraphDiff {
  added: Edge[];
  removed: Edge[];
  kept: Edge[];
}

export function diffGraphs(base: Edge[], cand: Edge[]): GraphDiff {
  const b = new Set(base.map(edgeKey));
  const c = new Set(cand.map(edgeKey));
  const byKey = new Map<string, Edge>();
  [...base, ...cand].forEach((e) => byKey.set(edgeKey(e), e));
  const added: Edge[] = [];
  const removed: Edge[] = [];
  const kept: Edge[] = [];
  for (const k of c) {
    const e = byKey.get(k) as Edge;
    if (b.has(k)) kept.push(e);
    else added.push(e);
  }
  for (const k of b) {
    if (!c.has(k)) removed.push(byKey.get(k) as Edge);
  }
  return { added, removed, kept };
}

export function gridXY(id: number, k: number): { x: number; y: number } {
  return { x: id % k, y: Math.floor(id / k) };
}
