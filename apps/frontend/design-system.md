# Citadel design system

The direction is **"Wide type, calm body"**. The interface is quiet and ordinary. The identity
lives in two places only: **wide Archivo type** for brand, headings and labels, and **one solid
ultramarine block** that marks where you are.

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
- The current company tile in the rail is **ink**, never accent: `--color-text` fill, `--color-surface`
  text, weight 900, a `--rail-bar` ink bar on the rail edge, `aria-current="true"`. Accent stays with
  the active nav item next to it.
- A company's status is a badge on its tile: building = spinner icon in `--color-warning`; failed
  and invalid = alert icon in `--color-danger`; unknown (graph unreachable) = cloud-off icon in
  `--color-text-muted`; ready and empty = no badge. The icon repeats what the accessible name says in
  words ("building", "last build failed", "config invalid", "graph unreachable").
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

- `AppShell` is the frame: company rail (`--rail-width`, 72px), sidebar (`--sidebar-width`, 240px),
  sticky top bar (`--topbar-height`), content up to `--content-max` (1280px).
- The rail is a full-height column of 48px tiles (`--control-lg`, `--radius-md`, `--space-2`
  apart) under the label "Brains". Its tile list scrolls without a visible scrollbar; the add tile
  below a hairline stays pinned. The current tile is scrolled into view when the company changes.
- Below 900px the rail and sidebar become one drawer side by side, opened from the top bar and
  closed by the scrim, Escape or a navigation. Below 640px the ask field takes its own row.
- Dashboard pages use a 12-column grid: main content spans 8, side panels span 4. At 1100px and
  below, panels go to 6 or full width; at 720px and below, everything is one column.
- Content is left-aligned. Nothing is centred except icons inside controls.
- The page never scrolls sideways. Long text wraps (`overflow-wrap: anywhere` for titles).

## 7. Components

Import from `$lib` (`import { Button, Card } from '$lib'`). Interactive primitives with focus
management (Tabs, Tooltip, Dialog, Menu, Select) are built on **bits-ui** and styled with our tokens. Do
not add another component library.

| Component    | Rule                                                                                           |
| ------------ | ---------------------------------------------------------------------------------------------- |
| `Button`     | Variants: `primary` (one per view), `secondary` (default), `ghost` (toolbars), `danger` (destructive). Sizes `sm` 32, `md` 40, `lg` 48. Icon-only needs `label`. The label says what happens ("Delete graph", not "OK"). |
| `Badge`      | Status words. The word carries the meaning; the tone repeats it.                               |
| `Banner`     | The state of a whole view (building, failed, invalid, unreachable) with its one action. Icon and title carry the state; tone repeats it. |
| `NodeChip`   | A graph node reference: type dot plus label. Type is in the accessible name.                   |
| `Avatar`     | Initials on the node colour of what it stands for. Always next to the name.                    |
| `Card`       | A titled panel. Title in wide type, optional description and actions. No nesting, no shadow.   |
| `Input`      | Always has a label (`hideLabel` keeps it for screen readers). `hint` explains; `error` says what is wrong and how to fix it. Disabled: sunken fill, muted text, no hover change, `not-allowed` cursor. `prefix` shows fixed mono text before the value (`brain_`, `github.com/`); `mono` sets the field in the mono face. |
| `Select`     | Pick one of a short list (bits-ui). Label always visible; `hint` explains, `error` says what to fix. Two or three options that need explaining are `ChoiceCard`s instead. |
| `ChoiceCard` | One option of a few that need a sentence each. A real radio in a label: selected = accent border, `--color-accent-soft` fill and a filled dot. Wrap the set in a `fieldset` with a `legend`. |
| `Checkbox`   | One yes/no with its label beside it. Checked is an ink box with a check, never accent, so it does not compete with the one accent block. |
| `TagInput`   | Several short values in one field. Enter or comma adds, paste splits, Backspace on empty removes the last; each tag has "Remove <tag>". `mono` for paths and ids. A comma inside `{}` stays in the tag (`*.{ts,tsx}`). Rules live in `src/lib/tags.ts`. |
| `Stepper`    | The steps of a flow. The current step is the one solid accent block with square corners; done steps show a check in an ink circle, later steps their number. |
| `Tabs`       | The selected tab is the solid accent block with square corners.                                |
| `Menu`       | Pick one of a set or run a command. Selected item shows a check.                               |
| `Tooltip`    | Extra hint only. Never the only place information lives. `detail` adds a mono second line (an id).                                       |
| `Dialog`     | Confirm destructive or blocking actions. Title is a question; the confirming action is last and named for what it does. |
| `Stat`       | A count with its label, inside a `<dl>`. For summaries, not decoration.                        |
| `EmptyState` | Says what will appear and how to get it, with one action.                                      |
| `CitedAnswer`, `GraphPath` | The answer pattern from section 1. Citation chips link to the numbered source.   |
| `EntityRow`, `WorkItemRow`, `ActivityBars` | List and comparison patterns for people, teams, systems and work items. |
| `CompanyForm` | The fields of a company file for one wizard step or all three (Settings). Edits the draft; the page validates and hands back `errors`, which show under the field their `loc` names. Errors no field shows are listed at the foot of the step, so nothing blocks without a reason. Rules in `src/lib/onboarding.ts`. |
| `SourceCard` | One source of a company. GitHub: repository, what to read, token note with "Check again", GitHub's answer; an error when the repository is not found or is private while the data is not `own`. Rate limits and outages are notes, never blockers. |
| `ConfigPreview` | The YAML the server will write, with the top-level keys of the current step marked (bar, tint and a line of words). Shows the last valid text while the form has errors, and says so. |
| `CompanyRail` | One tile per company brain; one click switches company and keeps the section you are on. Monogram 15px at width 118; ink for the current tile (section 3). Tooltip shows the name and `brain_<slug>` in mono. |
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
