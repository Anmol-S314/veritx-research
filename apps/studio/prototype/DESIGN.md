# Srota Studio prototype design contract

## Surface mode

**Operate.** A local desktop engineering workbench for inspecting explicit architecture objects, running scoped local declaration checks, and reviewing fixture-backed design workflows. The attached Stitch exports establish the visual direction; their unsupported engineering claims do not establish product truth.

## Visual authority

Preserve the light, restrained industrial identity of the supplied Design and Explore exports. Use one shared shell and consistent component vocabulary across Design, Explore, Verify, Deliver, and desktop settings. This is a reconstruction/refinement, not a new brand direction or pixel-for-pixel reproduction of contradictory exports.

## Tokens

- Ground: `#F2F4F6`.
- Surface: `#FFFFFF`.
- Toolbar: `#E9EDF1`.
- Border: `#C9D1DA`.
- Primary ink: `#1D242C`.
- Secondary ink: `#536170`.
- Accent: `#0F6C9E`.
- Selection: `#E3F0F8`.
- Error ink: `#A32928`.
- Warning ink: `#79540C`.
- Success ink: `#246847`.
- Primary type: locally served Inter.
- Technical type: locally served JetBrains Mono.
- Interface text: generally 12–14px; page title 18px.
- Borders: 1px; control radii: 3–4px; dialog radius: 6px.

`src/styles.css` is the implementation token source. Fonts are reused from existing repository assets with their OFL notices; there are no runtime font or icon CDN dependencies.

## Composition

Shared top header, six workspace slots, one contextual view rail, dominant work area, optional selection inspector, and one operational footer/drawer. Missing workspaces are visibly unavailable rather than represented by fake pages.

Primary desktop: 1440×900. Constrained desktop: 1280×800. At constrained widths, the inspector becomes an on-demand panel instead of squeezing the central view. Large tables use visible horizontal scrolling. Main content and the inspector scroll independently. Do not hide scrollbars or block text copying.

## Component and interaction language

Use native forms, semantic tables, named icon controls, consistent authored line icons, visible focus, and native dialog focus handling. Dense information is appropriate; decorative telemetry, pulsing status, giant KPI cards, duplicate rails, and chat-first navigation are not.

Meaningful signature interactions: selecting a graph point, endpoint, or comparison object carries its identity into related views; reviewing a change produces an actual local state update; branching preserves the complete previous draft. Route changes do not execute tools or adopt designs.

## Truthful visualizations

Chart coordinates, thresholds, axes, and frontier membership derive from the same numeric fixture. Missing metrics are not plotted at invented positions. Logical and placement-intent coordinates stay distinct. Physical area/power/qualification cannot be fabricated for visual completeness.

Keep execution, evidence availability, requirement outcomes, generation eligibility, and target qualification separate. All authored data remains visibly illustrative. Never upgrade a packet metric into a transaction requirement or a local declaration check into hardware verification.

## Implementation boundary

Local snapshots, browser state, JSON serialization/downloads, and in-browser declaration checks are real prototype operations. Simulation, formal proof, RTL generation, implementation qualification, agent execution, tool discovery, and enforceable execution budgets are not connected. Labels and disabled actions must preserve this distinction. Do not fake backend success with alerts or timers.
