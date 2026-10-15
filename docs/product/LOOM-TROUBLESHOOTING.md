# Loom Studio troubleshooting (current web checkout)

This guide describes the web Studio in this repository. It is **not** a Tauri desktop support guide: this build has no local-engine spawn, license verifier, updater, or signed installer. Instructions for those desktop subsystems cannot be supplied as if they existed. See the release-blocker list below.

## Project JSON will not load

- Keep the source file unchanged and retry with a copy. The editor validates the project before replacing its current graph.
- Check that it is a Loom project schema version supported by this build (currently v1), has valid JSON, and stays within the parser's 8 MiB and 128-level nesting admission limits. The validator shows the issue/path when available.
- If the file came from an unsupported version or contains invalid fields, do not hand-edit away unknown data in the only copy. Keep it for recovery and use a compatible schema/migration tool; this UI does not claim a general schema migration wizard.
- A rejected import should not be treated as a successful save. Verify the original file separately before retrying.

## Trace is malformed or truncated

- The strict JSONL trace parser rejects invalid JSON, missing required record fields, non-increasing cycles, invalid metric values, and unknown node/edge IDs with a source-line number. Inspect the indicated line and compare it with the project IDs and trace-event v1 contract under `contracts/loom/v1/`.
- A corrupt trace is not repaired by the parser. Preserve the original run artifact/log and re-export from the producer if available; do not relabel a valid prefix as a completed run.
- A single JSONL record is now bounded to 1 MiB and 64 nesting levels. This is an admission bound, not a maximum total trace size or a memory-eviction guarantee.
- The current web app does not have the packaged run manager / failure-artifact workflow needed to guarantee recovery of every truncated real-engine run.

## Save or download fails / browser state is missing

- Browser download prompts, browser policy, and available disk space govern downloaded project files. Retry the download and choose a writable destination; retain an unchanged in-memory tab until you have verified the downloaded file.
- Browser-local autosave is not a backup and is not a synchronized or project-ID-isolated recovery system. Do not clear site data or browser storage while trying to recover an unsaved project. Export a verified project JSON copy whenever possible.
- The current editor does not provide desktop permission-denied, disk-full, or autosave crash-recovery guarantees. If state is still visible, do not reload/close the tab before preserving it.

## Engine missing or incompatible

- The current build is web-only and fixture-backed; it cannot spawn a local simulator. The Simulation surface's mock preview is not a backend run or measured result. There is no supported engine installation/handshake recovery procedure in this build.
- Do not infer that changing a backend selector or refreshing the page repaired an engine. Use a separately qualified product build with an available, version-compatible engine when real execution is required.

## License or update problem

- No offline node-lock license UI or signed updater is implemented in this web checkout. There is no license state to repair and no update artifact to apply/roll back here. Do not provide a license file, key, or project data to an unverified site or service.
- Desktop licensing, update-channel, signature verification, and rollback procedures require the corresponding signed desktop product and must be documented and tested there before distribution.

## Release-owner follow-up

This guide is truthful for current web behavior but does not close tracker M11-45. Before that task can pass, add actionable, product-specific troubleshooting and recovery evidence for missing/incompatible packaged engine, license states, signed update failures/rollback, permission denial, and corrupt/truncated real traces on the actual supported desktop release path.
