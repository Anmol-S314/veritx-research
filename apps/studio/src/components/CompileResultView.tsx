import type { ReactElement } from 'react';
import CompileResult, {
  type CompileVariant,
} from './CompileResult/CompileResult';
import type { CompileResultView } from '../api';
import type { CompileResultGroup } from '../router';

export default function CompileResultViewPanel({ result, revisionId,
  projectId, variant, activeGroup, onGroupChange }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  variant?: CompileVariant;
  activeGroup?: CompileResultGroup;
  onGroupChange?: (group: string) => void;
}): ReactElement {
  return <CompileResult result={result} revisionId={revisionId}
    projectId={projectId} variant={variant} activeGroup={activeGroup}
    onGroupChange={onGroupChange} />;
}
