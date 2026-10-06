/** The provenance vocabulary exactly as
 *  `veritx_dse.application.value_provenance` serves it, as a fixture.
 *
 *  Two details in it are load-bearing and are pinned here on purpose. The four
 *  origins map onto artifact kinds through `origin_artifacts`, and the
 *  `capability` kind is in `artifact_kinds` but maps to NO origin — which is why
 *  a capability selection's origin cannot be resolved and the UI has to say so
 *  instead of borrowing one of the four words.
 *
 *  A fixture rather than a client constant: the whole point of the provenance
 *  badge is that the client holds no second copy of this vocabulary, so even the
 *  test's copy lives outside the product code.
 */
import type { ValueProvenanceView } from '../api/types';

export const SERVED_PROVENANCE: ValueProvenanceView = {
  schema_version: 1,
  type: 'srota/ValueProvenanceVocabulary',
  origins: ['AUTHORED', 'DERIVED', 'DECLARED', 'MEASURED'],
  freshness: ['CURRENT', 'STALE', 'FOREIGN_REVISION'],
  artifact_kinds: [
    'draft', 'topology', 'attachment', 'route', 'vc_assignment', 'certificate',
    'compile_result', 'run', 'traffic_matrix', 'evidence', 'backend',
    'capability',
  ],
  origin_meaning: {},
  freshness_meaning: {},
  origin_artifacts: {
    AUTHORED: ['draft'],
    DERIVED: [
      'topology', 'attachment', 'route', 'vc_assignment', 'certificate',
      'compile_result',
    ],
    DECLARED: ['draft', 'backend'],
    MEASURED: ['run', 'traffic_matrix', 'evidence'],
  },
  rule: 'Only MEASURED may be presented as a result.',
};