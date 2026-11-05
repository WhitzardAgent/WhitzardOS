# QitOS Studio design system

QitOS Studio is a focused workbench for starting agents and understanding what they did. It uses its own visual identity. The [Linear DESIGN.md analysis](https://github.com/voltagent/awesome-design-md/blob/main/design-md/linear.app/DESIGN.md) informs density and hierarchy; the existing qita dark palette informs continuity. OpenAI and DeepSeek Harness inform task and inspection flow, not branding.

## Principles

- Put the task, current state, and final answer in the primary reading path. Keep raw events one click away.
- A status label names a runtime fact. Use `unknown` when persistence or observation cannot prove a state.
- Show one primary action per context. Other actions stay visible as quiet controls, not hidden on hover.
- Use typography, spacing, and alignment before adding accent color. Color never carries status alone.

## Tokens

| Role | Dark | Light |
| --- | --- | --- |
| canvas | `#0b0d12` | `#f6f7f9` |
| sidebar | `#101219` | `#ffffff` |
| surface | `#151821` | `#ffffff` |
| raised surface | `#1c202b` | `#f0f2f6` |
| border | `#2b303d` | `#dfe3eb` |
| primary text | `#f4f5f8` | `#171b24` |
| secondary text | `#aeb5c3` | `#586172` |
| accent | `#8b90f7` | `#4f57b9` |
| focus ring | `#b4b8ff` | `#4049ac` |
| success | `#59bd85` | `#187448` |
| warning | `#e8b96a` | `#89550d` |
| danger | `#ed8585` | `#ad3535` |

UI text uses a system sans stack; identifiers, timestamps, and command fragments use a system monospace stack. Body is 14–15 px with at least 1.5 line height. Use a 4 px spacing unit, 8 px controls, 12 px panels, and restrained borders instead of decorative gradients. Motion is short and functional; respect `prefers-reduced-motion`.

## Structure and states

- Wide layout: 256 px navigation, flexible conversation with a 720 px reading measure, 360 px inspector. Navigation and inspector can collapse independently.
- Below 1180 px, inspector becomes an overlay. Below 720 px, navigation becomes a drawer and the composer stays reachable without horizontal scrolling.
- Agent home: compact agent cards with the registry's purpose and capability summary; recent sessions below.
- Session: task at top, ordered activity and final result in the center, timeline/tools/work graph/artifacts/diagnostics in inspector tabs.
- Loading, empty, offline, failed, paused, completed, and fact-unavailable states each have explicit copy and next action. No spinner is a substitute for an error.
- All buttons have default, hover, focus-visible, disabled, and pending states. Minimum touch target is 44 px on narrow screens. Menus and drawers close with Escape and restore focus.

## Conversation workbench revision (2026-11-06)

Codex is the primary interaction reference: a quiet left conversation rail,
one central reading column, persistent bottom composer, and a separate
inspection surface. DeepSeek Harness and ZCode inform the visibility of
recorded process and tool details. QitOS keeps its own name, purple accent,
status vocabulary and capability boundaries. Reference version is the public
product presentation available on 2026-11-05; no brand marks or page copy are
copied. Captured local acceptance screens are
[`studio-desktop-2026-11-06.png`](docs/internal/plans/studio_visual/studio-desktop-2026-11-06.png)
and [`studio-mobile-2026-11-06.png`](docs/internal/plans/studio_visual/studio-mobile-2026-11-06.png).
The light narrow-screen state is captured in
[`studio-mobile-light-2026-11-06.png`](docs/internal/plans/studio_visual/studio-mobile-light-2026-11-06.png).

| Region | Desktop | Narrow screen |
| --- | --- | --- |
| Navigation | 260 px fixed rail, paged list, search, new task | off-canvas drawer, Escape returns focus |
| Conversation | one flexible column, 790 px outer measure | full width, 19 px side padding |
| Inspector | 365 px optional column | overlay up to 400 px |
| Composer | anchored below scroll region, up to 730 px | 12 px inset, available above viewport edge |

The default language is Simplified Chinese, with a complete English switch.
Theme and language persist locally in the browser. The primary reading path is
user input → runtime status → Agent result → optional recorded process. A
terminal run with no displayable result says so. Unknown process state remains
unknown. File and diff tabs require an application declaration and are empty
until corresponding saved facts exist. Do not infer coding semantics from an
Agent ID or tool name.

| State | Primary surface | Inspector / action |
| --- | --- | --- |
| Loading | State what is loading in place | No placeholder facts |
| No registered Agents | Explain the local registry requirement | No launch control |
| Disconnected | Preserve already loaded facts and show a reconnect notice | Disable task submission until the service returns |
| Queued / running | Show the task and saved activity count | Follow durable records; do not infer progress from an open SSE connection |
| Paused / waiting input | Show the persisted lifecycle | Offer resume only after the server reports `can_resume` |
| Failed | Show a safe error code and recorded facts | No raw exception or private values |
| Completed | Show the saved final result or say it is unavailable | Keep the trajectory inspectable |
| Missing facts | Explicitly name the absence | Never render an invented tool call, graph, or metric |
