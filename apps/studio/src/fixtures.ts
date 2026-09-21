// Fixture loading. Studio boots from these contract-validated fixtures only.
// Every file here must pass scripts/validate_fixtures.py against the frozen
// contracts/srota/v1 schemas. No engine connectivity, no fetched data.
import type { FixtureBundle } from './types';

import compiledMesh from '../fixtures/compiled-mesh.json';
import invalidDesign from '../fixtures/invalid-design.json';
import backendUnavailable from '../fixtures/backend-unavailable.json';
import evaluatedDesign from '../fixtures/evaluated-design.json';
import optimizationStudy from '../fixtures/optimization-study.json';

function asBundle(doc: unknown): FixtureBundle {
  return doc as unknown as FixtureBundle;
}

export const FIXTURE_ORDER = [
  'compiled-mesh',
  'invalid-design',
  'backend-unavailable',
  'evaluated-design',
  'optimization-study',
] as const;

export type FixtureId = (typeof FIXTURE_ORDER)[number];

export const FIXTURES: Record<FixtureId, FixtureBundle> = {
  'compiled-mesh': asBundle(compiledMesh),
  'invalid-design': asBundle(invalidDesign),
  'backend-unavailable': asBundle(backendUnavailable),
  'evaluated-design': asBundle(evaluatedDesign),
  'optimization-study': asBundle(optimizationStudy),
};
