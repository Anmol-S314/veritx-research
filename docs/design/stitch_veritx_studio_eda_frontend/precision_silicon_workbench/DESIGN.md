---
name: Precision Silicon Workbench
colors:
  surface: '#f7f9ff'
  surface-dim: '#d4dae5'
  surface-bright: '#f7f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eef4ff'
  surface-container: '#e8eef9'
  surface-container-high: '#e2e9f4'
  surface-container-highest: '#dce3ee'
  on-surface: '#151c24'
  on-surface-variant: '#40484f'
  inverse-surface: '#2a3139'
  inverse-on-surface: '#eaf1fc'
  outline: '#707880'
  outline-variant: '#c0c7d0'
  surface-tint: '#006494'
  primary: '#00537c'
  on-primary: '#ffffff'
  primary-container: '#0f6c9e'
  on-primary-container: '#d0e8ff'
  inverse-primary: '#8fcdff'
  secondary: '#4e616a'
  on-secondary: '#ffffff'
  secondary-container: '#d2e6f1'
  on-secondary-container: '#546770'
  tertiary: '#444f5a'
  on-tertiary: '#ffffff'
  tertiary-container: '#5c6773'
  on-tertiary-container: '#dae6f4'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#cbe6ff'
  primary-fixed-dim: '#8fcdff'
  on-primary-fixed: '#001e30'
  on-primary-fixed-variant: '#004b71'
  secondary-fixed: '#d2e6f1'
  secondary-fixed-dim: '#b6c9d4'
  on-secondary-fixed: '#0a1e26'
  on-secondary-fixed-variant: '#374952'
  tertiary-fixed: '#d8e4f2'
  tertiary-fixed-dim: '#bcc8d5'
  on-tertiary-fixed: '#121d27'
  on-tertiary-fixed-variant: '#3d4853'
  background: '#f7f9ff'
  on-background: '#151c24'
  surface-variant: '#dce3ee'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-md:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.02em
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
  code-table:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: -0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.5rem
  margin: 0.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system establishes an uncompromising, high-density desktop engineering environment engineered explicitly for ASIC/FPGA system architects and interconnect performance engineers. It treats electronic design automation (EDA) workflows with the functional discipline of traditional verification workbenches (Synopsys, Cadence, Vivado) while instilling the typographic precision, deterministic visual ergonomics, and spatial restraint of modern high-performance desktop productivity software (Linear, VS Code).

The visual language is quiet, utilitarian, and deeply industrial. It fundamentally rejects consumer SaaS conventions—no floating decorative cards, rounded soft pill shapes, blurred glass surfaces, or fluorescent neon accents. Instead, the UI behaves as a calibrated hardware instrument: high visual stability, explicit 1px structural framing, deterministic data layout, and maximum data-per-pixel ratio. Visual emphasis is reserved strictly for signal paths, routing bottlenecks, validation warnings, and active clock/power domains.

## Colors

The color architecture is built around an analytical grayscale calibrated to reduce ocular strain during sustained multi-hour architecture analysis and timing-closure sessions. 

### Light Palette (Primary Base)
- **Application Shell / Canvas Outer**: `#F2F4F6`
- **Workbench Panel & Editor Surface**: `#FFFFFF`
- **Toolbar, Status Strip & Inspector Header**: `#E9EDF1`
- **Structural Grid & Perimeter Borders**: `#C9D1DA`
- **Primary Ink (Labels, Registers, Primary Metrics)**: `#1D242C`
- **Muted Ink (Metadata, Port Directions, Secondary Values)**: `#5D6874`
- **Active Node / Packet Focus Accent**: `#0F6C9E`
- **Active Mesh Selection Tint**: `#D3E7F2`

### Semantic Verification Tones
- **Success / Passed Assertions**: `#1D7A4C`
- **Warning / Flit Latency Degradation**: `#8A5D0C`
- **Error / Routing Deadlock / Timing Violation**: `#B3372C`
- **Diagnostic / Informational Events**: `#2456C4`

### Dark Palette Mapping
When the workbench switches to dark mode, surfaces invert to preserve photon neutrality:
- **Canvas Shell**: `#14171C`
- **Toolbar & Dock Frame**: `#1B2027`
- **Working Panels & Data Grids**: `#1E242C`
- **Separators & Matrix Dividers**: `#2E3640`
- **Primary Ink**: `#D7DDE5`
- **Muted Ink**: `#8B95A3`
- **Accent Active**: `#4DA3C4`
- **Selection Tint**: `#23424F`

## Typography

The typography implements a strict dual-font discipline:

1. **System Interface Sans (`Inter`)**: Governs spatial controls, window anchors, panel tab trees, and form properties. Body sizes cluster tight between 12px and 13px to preserve vertical space for multi-level routing hierarchies and configuration trees.
2. **Deterministic Technical Monospace (`JetBrains Mono`)**: Mandatory for all raw computational tokens. This includes AXI/NoC master/slave ports, memory-mapped offsets (e.g., `0x8000_0000`), packet payload dumps, clock cycle metrics, flit headers, injection rates, and compiler log streams. 

Tabular numerals (`tnum`) must remain perpetually engaged across all tables and scalar displays to eliminate horizontal jitter during live simulation playback.

## Layout & Spacing

Layout geometry follows an absolute 4px baseline rhythm. The UI conforms to a strict, docking-pane desktop model consisting of:
- A non-collapsible 36px Global Toolbar at the top boundary.
- Multi-pane splitters dividing the canvas (mesh topology viewer) from collapsible side drawers (property inspectors, routing matrices, latency histograms).
- A 24px persistent bottom Status Bar displaying engine cycle count, simulation convergence rate, active process health, and compilation status.
- Dockable console panels (Logs, Timing Violations, Flit Trace, DRC Alerts) anchored along the bottom viewport with user-movable horizontal drag dividers.

Gutter and margin dimensions default to compressed increments (4px to 8px) to maximize the active viewport allocated to high-radix mesh grids, toroidal topologies, and complex microarchitectural state inspectors.

## Elevation & Depth

Visual hierarchy is delivered entirely through surface tonality and 1px crisp borders, not shadow extrusion. The design relies on flat structural stratification:

- **Base Ground (Level 0)**: Canvas viewport `#F2F4F6` (Dark: `#14171C`).
- **Workbench Slabs (Level 1)**: Primary operational docks `#FFFFFF` (Dark: `#1E242C`) with 1px border stroke `#C9D1DA` (Dark: `#2E3640`).
- **Embedded Insets (Level -1)**: Sub-panels, code editors, and metric tables `#E9EDF1` (Dark: `#1B2027`).
- **Floating Overlays (Level 2 - Context Menus, Tooltips, Node Config Popovers)**: Single-pixel border paired with an ultra-subtle, non-diffuse ambient shadow: `box-shadow: 0 2px 4px 0 rgba(0, 0, 0, 0.08)`. Dark mode utilizes `box-shadow: 0 4px 8px 0 rgba(0, 0, 0, 0.35)`.

No blur effects, no translucent glass overlays, and no dynamic drop-shadow transitions.

## Shapes

Shapes prioritize industrial precision. Form follows utility:
- Standard interactive elements (inputs, toolbars, toggle buttons, modal panels, tab heads) strictly employ a 4px corner radius (`roundedness: 1`).
- Top-level application window shells and docking containers use crisp 0px or 2px internal corner transitions.
- Badges, status pills, and routing hop count indicators maintain a structured 4px corner box rather than pill-shaped cylinders, preserving consistent visual density alongside alphanumeric content.

## Components

### Buttons & Tool Controls
- **Standard Button**: 24px or 28px height. Background `#E9EDF1`, border 1px solid `#C9D1DA`, text `#1D242C`, 4px radius. Monospace or 12px medium sans typography.
- **Primary Action (Run Synthesis / Step Cycle)**: Background `#0F6C9E`, border 1px solid `#0F6C9E`, text `#FFFFFF`. Hover: `#0A5278`. Active: `#073C58`.
- **Icon Tool**: 24x24px boundary, 1px perimeter border, no background until hovered (10% tint of `#0F6C9E`).

### Input Fields & Steppers
- Input containers: 24px height. 1px solid `#C9D1DA`, inset padding `2px 6px`. Font: 11px `JetBrains Mono`. Focus state: 1px ring `#0F6C9E` without ambient blur. Error state: 1px ring `#B3372C`.
- Spin-boxes/Numeric adjusters: Micro-steppers aligned right with tactile 1px horizontal splitters.

### Data Tables & Latency Matrices
- Row height: Fixed 22px (dense) or 26px (standard).
- Alternating stripes: Avoided. Clear 1px bottom border `#C9D1DA` with 100% white rows.
- Selection: Full-row highlight using Selection Tint `#D3E7F2` (Dark: `#23424F`) and a left 2px vertical indicator in Primary Accent `#0F6C9E`.
- Numeric alignment: Tabular monospace, strictly aligned right.

### Topology Canvas Nodes
- Routers: Crisp rectangular boundaries (4px radius) with explicit port handles (North, South, East, West, Local 0, Local 1).
- Direct connection lanes: Orthogonal 1px vector paths. Color signifies buffer occupancy (Green &lt;50%, Amber &gt;80%, Red stalled).

### Collapsible Docks (Logs, DRC, Packet Traces)
- Header band: 24px height, uppercase 11px label font with chevron disclosure.
- Tab items: Square top corners with a crisp active bottom border highlight in `#0F6C9E`.