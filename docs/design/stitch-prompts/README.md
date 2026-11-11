# Srota Studio — Stitch prompt library

## Coverage and status

This library contains **46 self-contained view prompts**: the **45 proposed surfaces/flows** plus a dedicated **Analysis missing-artifact variant**.

**Status: prompts authored.** This is not an implementation inventory, completed-design approval, backend capability audit, or hardware qualification record. Existing application changes were not part of this documentation task. Each prompt requests its relevant normal, unsupported, partial, failure, or revision-conflict variants without requiring a separate document for every state.

## Use

1. Open the relevant Markdown file.
2. Copy the entire prompt into Stitch.
3. Attach the most recent approved, corrected screen as the visual reference.
4. Generate one surface and its specified variants at a time.
5. Keep illustrative datasets and revision identities consistent across views.
6. Classify depicted capabilities separately as implemented, partial, planned, unsupported, or unknown before integration.

Every view file contains its own product/design constraints; no separate shared preamble is required. [00-shared-contract.md](00-shared-contract.md) records the common contract for maintenance.

Do not attach confidential internal specifications or NDA artifacts to an external design service. These briefs intentionally avoid their contents.

## Suggested continuation

Complete New Evaluation if still pending. Then cover remaining Analysis specialists: Topology Overlay, Metrics, Trace, Logs & Artifacts, and Run Comparison.

Continue with Workloads & Requirements, remaining Design specialists, Explore, Verify, Deliver, shared desktop flows, and optional agent flows. Already briefed screens can be revisited from this library; “prompt exists” does not mean a generated screen has been reviewed.

Keep brief chat updates and use these files for detailed prompts. Consolidate overlapping layouts after coverage, but correct fabricated capabilities and contradictory evidence immediately.

## View inventory

### Design — 9 surfaces

- [Design — Fabric Topology](design-fabric-topology.md)
- [Design — System / Block Diagram](design-system-block-diagram.md)
- [Design — Hardware Endpoints](design-hardware-endpoints.md)
- [Design — IP Catalog](design-ip-catalog.md)
- [Design — Initiator–Target Mapping](design-initiator-target-mapping.md)
- [Design — Address Map](design-address-map.md)
- [Design — Clock & Power Domains](design-clock-power-domains.md)
- [Design — Placement Constraints](design-placement-constraints.md)
- [Design — Proposed Change Review](design-proposed-change-review.md)

### Workloads & Requirements — 6 surfaces

- [Workloads & Requirements — Workload Library](workloads-library.md)
- [Workloads & Requirements — Structured Workload Editor](workloads-structured-editor.md)
- [Workloads & Requirements — Requirements Editor](workloads-requirements-editor.md)
- [Workloads & Requirements — Endpoint Bindings](workloads-endpoint-bindings.md)
- [Workloads & Requirements — Assumptions & Model Inputs](workloads-assumptions-inputs.md)
- [Workloads & Requirements — Validation / Lowering Preview](workloads-validation-lowering.md)

### Analysis — 8 surfaces + 1 state variant

- [Analysis — Summary](analysis-summary.md)
- [Analysis — Traffic Matrix](analysis-traffic-matrix.md)
- [Analysis — Topology Overlay](analysis-topology-overlay.md)
- [Analysis — Metrics](analysis-metrics.md)
- [Analysis — Trace Viewer](analysis-trace.md)
- [Analysis — Logs & Artifacts](analysis-logs-artifacts.md)
- [Analysis — Run Comparison](analysis-run-comparison.md)
- [Analysis — Missing Artifact / Not Recorded (state variant)](analysis-missing-artifact.md)
- [Analysis — New Evaluation](analysis-new-evaluation.md)

### Explore — 5 surfaces

- [Explore — Versioned Exploration Brief](explore-brief.md)
- [Explore — Study Execution & Budgets](explore-progress-budgets.md)
- [Explore — Candidate Results & Trade-offs](explore-candidate-results.md)
- [Explore — Candidate Comparison](explore-candidate-comparison.md)
- [Explore — Candidate Adoption / Branch](explore-candidate-adoption.md)

### Verify — 5 surfaces

- [Verify — Evidence Overview](verify-evidence-overview.md)
- [Verify — Configuration Support Checks](verify-configuration-support.md)
- [Verify — Check Setup & Results](verify-check-results.md)
- [Verify — Outstanding Obligations](verify-outstanding-obligations.md)
- [Verify — Evidence Detail / Claim Scope](verify-evidence-detail.md)

### Deliver — 5 surfaces

- [Deliver — Output Readiness](deliver-readiness.md)
- [Deliver — Output Configuration](deliver-output-configuration.md)
- [Deliver — Generation Job](deliver-generation-job.md)
- [Deliver — Package Review & Manifest](deliver-package-review.md)
- [Deliver — Artifact Inspection & Export](deliver-artifact-inspection.md)

### Shared desktop — 3 surfaces

- [Shared — Projects, Revisions & Recovery](shared-project-management.md)
- [Shared — Environment & Local Settings](shared-environment-settings.md)
- [Shared — Jobs, Problems & Logs Drawer](shared-jobs-problems.md)

### Optional agents — 4 surfaces

- [Optional Agents — Contextual Assistant](agents-contextual-assistant.md)
- [Optional Agents — Requirements to Editable Workload](agents-workload-translation.md)
- [Optional Agents — Runtime Connection & Permissions](agents-runtime-permissions.md)
- [Optional Agents — Approvals, Scope Changes & Activity](agents-approvals-activity.md)

## Shared review checklist

- Manual operation works without AI; no required cloud account.
- Six workspaces remain contextual views, not a mandatory wizard.
- No duplicate global/context sidebars, hidden scrollbars, tiny essential labels, or non-copyable identifiers.
- Every result identifies inputs, definition, units, scope, source, and limitations.
- Execution, requirement outcome, artifact availability, generation eligibility, and implementation qualification stay separate.
- Historical evidence remains bound to its immutable inputs.
- Demand, injection, delivery, connectivity, permissions, routing, and observed paths are not substituted.
- Missing measurements do not become zeros, clean checks, or failing requirements.
- Hardware requirements stay separate from execution/search budgets.
- Included operations use the approved brief; scope expansion and candidate adoption require the appropriate review.
- Logical drawing edits do not silently change placement constraints.
- ASIC/FPGA qualification and model/RTL support are independent.
- No invented flags, versions, proofs, artifacts, overheads, process estimates, or achieved timing.
- No fake backend success through timers or alerts.
- Read-only artifact previews never execute untrusted generated content.
- Unsupported descriptions remain inspectable/exportable at their actual scope.
- Prompt coverage does not promise complete accelerator generation or protected RTL.
