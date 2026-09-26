---
version: alpha
name: VERITX Studio
description: Semiconductor NoC fabric engineering console for compiling, verifying and evaluating fabrics. Dense, flat, evidence-first; monospace identities; no decorative chrome.
colors:
  bg: "#14171c"
  bg-raise: "#1b2027"
  bg-card: "#1e242c"
  border: "#2e3640"
  text: "#d7dde5"
  muted: "#8b95a3"
  accent: "#4da3c4"
  accent-dim: "#23424f"
  ok: "#4caf7d"
  ok-bg: "#16281f"
  bad: "#e0655a"
  bad-bg: "#2c1a18"
  warn: "#d9a441"
  warn-bg: "#2a2113"
  info: "#6aa8ff"
  input-bg: "#12151a"
typography:
  mono:
    fontFamily: "ui-monospace, SF Mono, Cascadia Code, Menlo, Consolas, monospace"
---

## Overview

VERITX Studio is the product surface of the VERITX fabric compiler: a
hardware/system engineer compiles a design intent, inspects the verification
certificate, runs a qualified simulation, and follows each measured number
back to its evidence. The interface is a semiconductor engineering tool —
dense but readable, flat, with real units and monospace identities. It
deliberately avoids glassmorphism, gradients, glow effects and decorative
charts.

## Colors

Use `bg` for the page, `bg-raise` for the persistent context header and
status bars, and `bg-card` for panels. `text` is body copy; `muted` is
secondary metadata. `accent` marks the single active/primary affordance per
view (active navigation, primary action, focused control). Status roles are
`ok` / `bad` / `warn` / `info`; their `-bg` pairs are used only as banners,
never as fills.

## Themes

The interface ships dark and light. Frontmatter carries the dark (default)
values; light values are:

| token | light |
|---|---|
| bg | #f2f4f6 |
| bg-raise | #e9edf1 |
| bg-card | #ffffff |
| border | #d3d9e0 |
| text | #1d242c |
| muted | #5d6874 |
| accent | #0f6c9e |
| accent-dim | #d3e7f2 |
| ok | #1d7a4c |
| ok-bg | #e2f2e9 |
| bad | #b3372c |
| bad-bg | #f9e3e0 |
| warn | #9a6b12 |
| warn-bg | #f7ecd2 |
| info | #2456c4 |
| input-bg | #f6f8fa |

## Typography

Two families, both self-hosted variable woff2 (latin subset), so the tool
works without a font CDN:

- `sans` (Inter) for prose, labels and controls;
- `mono` (JetBrains Mono) for every machine identity and measured quantity
  — hashes, metric values, resource ids, job states.

A small semantic scale: micro 11, label 12, body 13, body-lg 16, title 15,
display 20. Headings 1.15 line-height, body 1.5. Small uppercase labels
carry positive tracking; large headings slightly negative. Data and
identities render with tabular figures so columns do not shift. Headings
balance; body and list text is pretty-wrapped. Text is antialiased once on
the root. On small screens inputs render at 16px so iOS does not zoom.

## Layout

A three-region engineering shell: a sticky topbar (brand, live context
strip, actions), a left numbered rail (00–09) for navigation, and a
workspace. Inside a project the workspace opens with the pipeline bar
(Intent → Fabric → Certificate → Execute → Decide), then the page. Machine
identities are truncated with the full value in a tooltip, never dropped.

## Components

Interactive navigation is a real anchor (`<a href>`), not a button with an
onClick: the rail, pipeline links and run links are links so keyboard,
middle-click and deep-linking work. Buttons are reserved for actions
(compile, run simulation, create project). Every focusable control has a
visible focus ring. Loading and job states announce themselves with
`role="status"`.

The topology / traffic view is a 3D scene (Three.js, lazy-loaded) of the
declared fabric: orbitable routers, mesh links and attachments, with a 2D
fallback and an artifact strip bound to the compiler's real hashes. Only
`structure` is rendered; every other overlay names the artifact it needs
and is never fabricated.

## Do's and Don'ts

- Do show a status as a `StatusBadge` with its exact engine verdict
  (`SATISFIED`, `VIOLATED`, `UNMEASURABLE`, `PASS`, `REFUSED`); never
  collapse distinct states into one colour or a single "something failed".
- Do keep the active context (project, revision, workload, latest run,
  next action) visible on every project page.
- Don't show a metric, overlay or heatmap that has no backing artifact.
- Don't use gradients, glow, or purple; the accent is the only accent.
- Don't invent a human name in place of a machine identity; carry both.
