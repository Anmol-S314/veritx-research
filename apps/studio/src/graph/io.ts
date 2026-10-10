/** Web-only export central (P7 without Tauri): browser downloads. */
import type { LoomProject } from './project';
import { serializeProject } from './project';

export function download(filename: string, text: string, mime = 'application/json'): void {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function exportProjectJson(project: LoomProject): void {
  download('project.json', serializeProject(project));
}

export function nodesToCsv(project: LoomProject): string {
  const rows = ['id,x,y,role,ports,clock,vc_depth,vc_count'];
  for (const n of project.nodes) {
    const vc = (n.vc ?? {}) as Record<string, unknown>;
    rows.push([n.id, n.x, n.y, n.role, n.ports, n.clock ?? '', vc.depth ?? '', vc.count ?? ''].join(','));
  }
  return `${rows.join('\n')}\n`;
}

export function csvToNodePatches(csv: string): { id: string; role?: string; ports?: number; clock?: string | null }[] {
  const lines = csv.trim().split('\n');
  const out: { id: string; role?: string; ports?: number; clock?: string | null }[] = [];
  for (const line of lines.slice(1)) {
    const [id, , , role, ports, clock] = line.split(',');
    if (!id) continue;
    const patch: { id: string; role?: string; ports?: number; clock?: string | null } = { id: id.trim() };
    if (role?.trim()) patch.role = role.trim();
    const p = Number(ports);
    if (Number.isInteger(p) && p > 0) patch.ports = p;
    if (clock !== undefined) patch.clock = clock.trim() === '' ? null : clock.trim();
    out.push(patch);
  }
  return out;
}

export function exportSvgPng(svg: SVGSVGElement, filename: string): void {
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = svg.clientWidth * 2 || 1200;
    canvas.height = svg.clientHeight * 2 || 800;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = getComputedStyle(svg).getPropertyValue('background-color') || '#14171c';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(img.src);
    canvas.toBlob((b) => {
      if (!b) return;
      const url = URL.createObjectURL(b);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, 'image/png');
  };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
}
