# Citadel design system

Direction **H, "Wide type, calm body"**, picked from the round 2 directions canvas
(<https://claude.ai/artifact/4GQhEe9KcnEu36jxJhr4xh>). The interface is quiet and ordinary. The
identity lives in two places only: **wide Archivo type** for brand, headings and labels, and
**one solid ultramarine block** that marks where you are.

This file is the rulebook. The tokens are in `src/lib/styles/tokens.css`, the components in
`src/lib/components/`, and the live gallery at `/components`. When code and this file disagree,
fix one of them in the same change.

## 1. Who it is for and what every screen must do

Citadel turns a company's engineering activity into a graph that people and agents query. The
people using it are engineers and engineering leads asking "why", "who" and "what changed".

Every screen follows three product rules:

1. **Every answer shows its evidence.** An answer is never shown without its numbered sources
   and its graph path (`CitedAnswer`). No source, no answer.
2. **Summary before detail.** A view opens with counts or the answer, then the lists behind it.
3. **Name things the way the graph does.** Use the node labels (Person, Team, System, Work item,
   Change, Document) and keep relationship names in their schema form (`AUTHORED`, `TOUCHES`).

## 2. Principles

- **Calm body, one loud element.** Per view, only one thing is solid accent: the active nav item
  or the selected tab (and the one primary button). Everything else is surface, hairline and ink.
- **Width is hierarchy.** Archivo's width axis does the work that colour and size do elsewhere:
  brand 125, headings 118, labels 112, body 100. Do not add a second typeface for display.
- **Colour means something.** Accent means action or "you are here". Status colours mean status.
  Node colours mean graph type. Nothing is coloured for decoration.
- **Never colour alone.** Every state also has a word, an icon, a weight or a fill change.
- **No decoration.** No gradients, no shadows on panels, no illustrations, no emoji.

## 3. Colour

All colours are tokens in `tokens.css`, with light values on `:root` and dark values for
`prefers-color-scheme: dark` and `html[data-theme="dark"]`. Components never use a literal colour.

| Token                                   | Use                                                         |
| --------------------------------------- | ----------------------------------------------------------- |
| `--color-ground`                        | Page background behind panels (stone).                      |
| `--color-surface`                       | Panels, cards, inputs, sidebar, top bar.                    |
| `--color-surface-raised`                | Floating layers only: menus, dialogs.                       |
| `--color-surface-sunken`                | Wells and hover fills: tracks, ghost hover, neutral badges. |
| `--color-text`                          | Primary text (ink).                                         |
| `--color-text-muted`                    | Secondary text. Meets 4.5:1 on surface in both themes.      |
| `--color-text-faint`                    | Placeholders and inert items only. Never essential text.    |
| `--color-line` / `--color-line-strong`  | Hairlines between items / borders of controls.              |
| `--color-accent` (+ `-hover`, `-soft`)  | Primary action, active nav, selected tab, links, citations. |
| `--color-on-accent`                     | Text and icons on an accent fill.                           |
| `--color-success` / `warning` / `danger` (+ `-soft`) | Status only. Never as an accent or for emphasis. |
| `--node-person` … `--node-document`     | Graph node types. Only for dots, avatars, bars and graph marks. |

Rules:

- The accent fill appears at most once per region: active nav item, selected tab, primary button.
- `-soft` tints are for selected rows and citation chips, with text in the matching strong colour.
- Node colours are for marks (dots, bars, avatar initials), never for body text or buttons.
- Work item state maps to badges as: open = success, merged = accent, closed = neutral.

## 4. Type

One family, **Archivo Variable** (`@fontsource-variable/archivo/wdth.css`, weights 100 to 900,
widths 62 to 125). **IBM Plex Mono** is only for ids, paths, shas, graph names and relationship
names.

| Token        | Size | Use                                  |
| ------------ | ---- | ------------------------------------ |
| `--text-3xl` | 32   | Stat values                          |
| `--text-2xl` | 24   | Page title (one per page)            |
| `--text-xl`  | 20   | Dialog titles, brand                 |
| `--text-lg`  | 16   | Answer text, questions, body copy    |
| `--text-md`  | 14   | Interface default                    |
| `--text-sm`  | 13   | Secondary rows, labels               |
| `--text-xs`  | 12   | Meta lines, chips, badges            |

| Role      | Width (`font-variation-settings: 'wdth'`) | Weight      |
| --------- | ----------------------------------------- | ----------- |
| Brand, page title | `--width-brand` 125               | 900 (black) |
| Headings  | `--width-heading` 118                      | 700         |
| Labels, section headings, field labels | `--width-label` 112 | 600 to 700 |
| Body      | `--width-body` 100                         | 400 to 500  |

Rules:

- Sentence case everywhere. No all-caps labels, no letter-spaced eyebrows. (Relationship names
  like `AUTHORED` are data, not labels, and stay as the schema writes them.)
- Answer text is `--text-lg` at `--leading-body` and at most 66 characters wide.
- Numbers that line up use `.tabular` (`font-variant-numeric: tabular-nums`).
- One `h1` per page. Card titles are `h2`. Use headings in order.

## 5. Space, shape and depth

- **Space** is a 4px grid: `--space-1` (4) to `--space-12` (48). Use `gap` on flex and grid
  parents rather than margins on children.
- **Radius**: `--radius-md` (8) for buttons, inputs, cards and menus. `--radius-sm` (4) for
  chips, badges and citations. `--radius-full` for avatars and node pills. `--radius-none` only
  for the solid accent block (active nav item, selected tab): square corners are part of the
  signature, so do not round them.
- **Borders**: 1px hairlines. Panels are separated by hairlines on the stone ground.
- **Depth**: panels never cast shadows and cards never nest. Only floating layers (menus,
  dialogs, tooltips) use `--shadow-overlay`.

## 6. Layout

- `AppShell` is the frame: sidebar (`--sidebar-width`, 240px), sticky top bar
  (`--topbar-height`), content up to `--content-max` (1280px).
- Below 900px the sidebar becomes a drawer, opened from the top bar and closed by the scrim,
  Escape or a navigation. Below 640px the ask field takes its own row.
- Dashboard pages use a 12-column grid: main content spans 8, side panels span 4. At 1100px and
  below, panels go to 6 or full width; at 720px and below, everything is one column.
- Content is left-aligned. Nothing is centred except icons inside controls.
- The page never scrolls sideways. Long text wraps (`overflow-wrap: anywhere` for titles).

## 7. Components

Import from `$lib` (`import { Button, Card } from '$lib'`). Interactive primitives with focus
management (Tabs, Tooltip, Dialog, Menu) are built on **bits-ui** and styled with our tokens. Do
not add another component library.

| Component    | Rule                                                                                           |
| ------------ | ---------------------------------------------------------------------------------------------- |
| `Button`     | Variants: `primary` (one per view), `secondary` (default), `ghost` (toolbars), `danger` (destructive). Sizes `sm` 32, `md` 40, `lg` 48. Icon-only needs `label`. The label says what happens ("Delete graph", not "OK"). |
| `Badge`      | Status words. The word carries the meaning; the tone repeats it.                               |
| `NodeChip`   | A graph node reference: type dot plus label. Type is in the accessible name.                   |
| `Avatar`     | Initials on the node colour of what it stands for. Always next to the name.                    |
| `Card`       | A titled panel. Title in wide type, optional description and actions. No nesting, no shadow.   |
| `Input`      | Always has a label (`hideLabel` keeps it for screen readers). `hint` explains; `error` says what is wrong and how to fix it. |
| `Tabs`       | The selected tab is the solid accent block with square corners.                                |
| `Menu`       | Pick one of a set or run a command. Selected item shows a check.                               |
| `Tooltip`    | Extra hint only. Never the only place information lives.                                       |
| `Dialog`     | Confirm destructive or blocking actions. Title is a question; the confirming action is last and named for what it does. |
| `Stat`       | A count with its label, inside a `<dl>`. For summaries, not decoration.                        |
| `EmptyState` | Says what will appear and how to get it, with one action.                                      |
| `CitedAnswer`, `GraphPath` | The answer pattern from section 1. Citation chips link to the numbered source.   |
| `EntityRow`, `WorkItemRow`, `ActivityBars` | List and comparison patterns for people, teams, systems and work items. |
| `AppShell`, `Sidebar`, `Topbar`, `ThemeToggle` | The frame. Nav items for unbuilt sections stay visible, inert, marked "Soon". |

Adding a component:

1. Check that an existing component cannot be extended first.
2. Put it in `ui/` (generic), `brain/` (graph and answer patterns) or `layout/` (frame).
3. Use only tokens. Write a `@component` comment that says when to use it.
4. Add it to `src/lib/index.ts` and to the `/components` gallery with its states (default,
   hover, focus, disabled, error, empty, long text), in both themes.
5. Run `pnpm check` and `npx @sveltejs/mcp svelte-autofixer <file>`.

## 8. Accessibility floor

- Text contrast at least 4.5:1, large text and UI marks at least 3:1, in both themes.
- Every control is reachable and usable by keyboard and shows `:focus-visible` (2px accent ring).
- Hit targets: 40px default, 32px minimum for dense toolbars.
- Selected and current states use fill or weight plus `aria-current` or `aria-selected`, never
  colour alone.
- Icons next to text are `aria-hidden`; icon-only controls have an accessible name.
- Motion is short (120 to 180ms, ease-out), only answers a user action, and is removed under
  `prefers-reduced-motion`.

## 9. Writing

- Name things by what the user knows: "Sync now", "Open graph", "Company graph".
- Buttons are verbs that say what happens, and the result uses the same word ("Delete graph",
  then "Graph deleted").
- Errors say what went wrong and what to do: "Use lowercase letters, digits and dashes only".
- Empty states invite the next step instead of describing emptiness.
- Dates in tables and meta lines: `6 Feb`; with a year when it is not this year.

## 10. Theme

The theme follows the OS by default. `ThemeToggle` pins light or dark by setting
`<html data-theme>` and stores it in `localStorage` (`citadel-theme`). `app.html` applies the
stored value before first paint. Both themes are designed, not inverted: check every change in
both.
