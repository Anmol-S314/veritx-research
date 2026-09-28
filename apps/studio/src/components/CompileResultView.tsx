import type { ReactElement } from 'react';
import CompileResult, {
  type CompileVariant,
} from './CompileResult/CompileResult';
import type { CompileResultView } from '../api';

/** Backwards-compatible entry point: the console lives in
 * CompileResult/ split by responsibility. */
export default function CompileResultViewPanel({ result, revisionId,
  projectId, variant }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  variant?: CompileVariant;
}): ReactElement {
  return <CompileResult result={result} revisionId={revisionId}
                        projectId={projectId} variant={variant} />;
}
