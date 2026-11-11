import { gateway, type CanonicalRoute } from './gateway';

// One route-resolution loop for both the sweep and the playback. Keys are `src:dst` router ids;
// the gateway answers with the revision's declared routing class. Failures are reported, never
// filled in with a guessed route.
export type ResolvedRoutes = { routes: Map<string, CanonicalRoute>; failed: string[]; unterminated: string[] };

export async function resolveRoutes(revisionId: string, keys: string[], concurrency = 4, onProgress?: (done: number, total: number) => void): Promise<ResolvedRoutes> {
  const routes = new Map<string, CanonicalRoute>();
  const failed: string[] = [];
  const unterminated: string[] = [];
  const queue = [...keys];
  let done = 0;
  const worker = async () => {
    while (queue.length) {
      const key = queue.shift()!;
      const [src, dst] = key.split(':').map(Number);
      try {
        const route = await gateway.route(revisionId, { src, dst });
        if (route.terminates) routes.set(key, route);
        else unterminated.push(key);
      } catch {
        failed.push(key);
      }
      done += 1;
      onProgress?.(done, keys.length);
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, concurrency) }, () => worker()));
  return { routes, failed, unterminated };
}
