import { canonEdge, type Edge } from './graph';

export interface StudyDraft {
  id: string;
  name: string;
  method: string;
  createdAt: string;
  base: 'mesh' | 'explicit' | 'previous-candidate';
  baseNodes: number;
  baseK: number;
  traffic: string;
  constraints: Record<string, string | number>;
  params: Record<string, string | number>;
  cli: string[] | null;
  cliNote: string;
}

export interface LocalCandidate {
  id: string;
  studyId: string;
  label: string;
  method: string;
  nodes: number;
  links: Edge[];
  generatorObjective: number | null;
  generatorNote: string;
  seed: number | null;
  importedAt: string;
  backendCandidateId: string | null;
  backendOptimizationId: string | null;
  compileState: 'NOT_COMPILED' | 'COMPILED';
  verifyState: 'NOT_VERIFIED' | 'VERIFIED';
}

const STUDY_KEY = 'veritx.synth.studies.v1';
const CAND_KEY = 'veritx.synth.candidates.v1';

function read<T>(key: string): T[] {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const v = JSON.parse(raw) as unknown;
    return Array.isArray(v) ? (v as T[]) : [];
  } catch {
    return [];
  }
}

function write(key: string, rows: unknown[]): void {
  window.localStorage.setItem(key, JSON.stringify(rows));
}

function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
}

export function listStudies(): StudyDraft[] {
  return read<StudyDraft>(STUDY_KEY);
}

export function saveStudy(draft: Omit<StudyDraft, 'id' | 'createdAt'>): StudyDraft {
  const row: StudyDraft = {
    ...draft,
    id: uid('std'),
    createdAt: new Date().toISOString(),
  };
  const rows = listStudies();
  rows.push(row);
  write(STUDY_KEY, rows);
  return row;
}

export function deleteStudy(id: string): void {
  write(STUDY_KEY, listStudies().filter((s) => s.id !== id));
  write(CAND_KEY, listCandidates().filter((c) => c.studyId !== id));
}

export function listCandidates(studyId?: string): LocalCandidate[] {
  const rows = read<LocalCandidate>(CAND_KEY);
  return studyId ? rows.filter((c) => c.studyId === studyId) : rows;
}

export function saveCandidate(
  cand: Omit<LocalCandidate, 'id' | 'importedAt'>,
): LocalCandidate {
  const row: LocalCandidate = {
    ...cand,
    links: cand.links.map(([u, v]) => canonEdge(u, v)),
    id: uid('cand'),
    importedAt: new Date().toISOString(),
  };
  const rows = read<LocalCandidate>(CAND_KEY);
  rows.push(row);
  write(CAND_KEY, rows);
  return row;
}

export function deleteCandidate(id: string): void {
  write(CAND_KEY, listCandidates().filter((c) => c.id !== id));
}
