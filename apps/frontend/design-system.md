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
| `--graph-edge`                          | Links between nodes on a graph.                             |
| `--graph-territory` (+ `-alt`)          | The two tones graph territories alternate between. Tone, never hue. |

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
  `--color-accent-soft` is also the fill of the user's question bubble on the Ask page, with ink text.
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
- The Graph page (`/c/<slug>/graph`) is the one exception to `--content-max`: `AppShell` drops
  the width cap and the padding, and the page fills the height under the top bar. Its bar holds the
  title, Find, a one-line count and the Filters and List buttons; the inspector (20rem) opens on
  the right when a node is selected, and below 900px it takes the lower part of the page.

### The graph map (design direction D, "Territories")

- Every node sits in the territory of the system it touches most (rules in
  `apps/brain/brain/graph_view.py`): the nine biggest systems, one territory for the smaller
  ones, and a dashed outline for work linked to no code. The layout numbers are in `src/lib/graph.ts`.
- Territories are **tonal**, never hue: `--graph-territory` and `--graph-territory-alt`
  alternate, outlined in `--color-line`. Hue stays reserved for node kinds.
- Routes between territories are ink (`--color-text`) at low opacity, as wide as the links they
  carry; fewer than 10 links draw no route. Links inside a territory are `--graph-edge`, faint.
- Territory names are wide black type on the outline's top edge, with a surface halo so they read
  over dots. Small territories drop the count, the smallest drop the name until you zoom in.
- **Selected is an ink ring**, never accent (the Graph nav item holds the accent). A selection
  lights its node, neighbours and links, outlines the territories it reaches in ink, and dims
  everything else. Hover is a thinner ink ring and a raised name label.
- Filters hide nodes in place; the map never moves under them. Only Bots refetches and lays out
  again, because it adds nodes. Comments are counted on their work items, not drawn.
- The canvas is hidden from assistive tech, which reads a one-line summary. Find (a combobox)
  and List (a table, most linked first) are the keyboard way to every node, and both select on
  the map. The selection is kept in the URL as `?focus=<uid>`.
- No motion: the layout is worked out before the map is shown (in a worker), and panning to a
  selection jumps.

### The Systems page and the agent trail (design direction A)

- The Systems page is the Graph page's map with an agent's run drawn over it. It answers "where is
  an agent working, and what has it done on the graph" (canvas: Systems · Agent at work).
- **The agent is ink, never accent or status.** Each step sits on the node it was about (the system
  it read, the node it opened), else on the first drawn node it returned when all it returned
  sits in one territory. A step spread over several (listing the systems) gets no point: its nodes
  are lit and the rail says "across the graph". Its number is an ink
  disc (`--color-text` with `--color-surface` text). One ink line joins the steps in order.
  Steps in a row on one node share a disc ("1, 2").
- While the run is going, the agent's node has an ink ring, its territory an ink outline, and an
  ink label says who and what ("Ask agent · Reading recent work on Auth"). Nothing moves on its
  own: the trail grows as steps land, and the map is not laid out again.
- The nodes a run touched stay bright and the rest dim, as a selection does. A selection still
  wins over the trail.
- The rail lists every step, numbered as on the map. A ring is the step running now. A dash marks
  a step with nothing on the map (the answer check, an MCP call), and it says "not on the map".
- The page opens on a running run, else the newest. A run that starts takes the map back from a
  run picked in "Other runs". Runs are read every 1.5 s while one is going, every 6 s otherwise,
  every 20 s in a hidden tab.

### The Ask page (design direction J + L)

- **One lane per question** (`AskLane`). A strip across the top (`Q1`, the question, how it went),
  the conversation on the left (the question as a bubble, the ledger, the answer, Copy answer, the
  thumbs and Replay walk) and that question's own walk on the right. Lanes stack in one scroller;
  nothing is replaced when a follow-up arrives.
- **The walk is sticky per lane.** It stays in view while its lane scrolls by and leaves with it.
  A follow-up's walk starts from what the earlier questions found: those nodes are dashed and faint
  until a step reaches them.
- **Walks draw first near the screen, then stay drawn.** A lane draws its walk the first time it
  comes within 200px of the scroller's view (IntersectionObserver); until then a box of the same
  size (canvas and caption line) keeps its place. A drawn walk is never drawn again from scratch:
  scrolling back or unfolding shows it as it was, with no new layout or animation.
- **One splitter for every lane** (`Splitter`), between the conversation and the walk column. Width
  is a share of the page: 38% by default, 320px to 65% when dragged, and the chat column keeps at
  least 420px (on a narrow page the widest share drops, but never below 320px). The width is kept
  in this browser (`citadel-ask-walk`). A double-click puts it back to 38%. Keys: arrows move it
  by a step, Shift by a bigger step, Home and End go to the narrowest and the widest, Enter folds
  and unfolds. Dragging more than 80px past the narrowest width folds the column.
- **Folded, the column is a strip** (`--walk-strip`, 48px) with a marker per lane: a status dot and
  the node count. Folding keeps the width: unfolding (by key, button or drag) brings back the
  width from before. The splitter stays, so one drag opens it again.
- **"Hide the walks" / "Show the walks"**: an icon button at the top of the walk column (in the
  page head, wide screens only) folds and opens the column too, and saves the choice like the
  splitter does.
- **Progress for screen readers.** While a lane's answer runs, a hidden polite live region says
  the step under way (the ledger's sentence, "Reading recent work on Auth"), or "Writing the
  answer" while only the answer check runs.
- **A new question scrolls its lane to the top** (pin-to-top), and the newest lane is at least as
  tall as the scroller so there is room to do it. Further than 80px from the end, a "Jump to latest"
  pill shows, left-aligned with the chat column.
- **Below 1100px** the page is one column: the walk goes under the conversation, not sticky, and
  there is no splitter.
- **The sidebar folds** to its icons (`--sidebar-folded`, 56px) from the top bar's fold button or
  the `[` key, and the choice is kept (`citadel-sidebar`). Folded items are named by tooltips and
  for screen readers. The fold animates: the sidebar column's width eases over `--duration-base`,
  the labels fade out at once (`--duration-fast`) and fade back in once there is room, folded
  headings turn into the hairlines between groups, and the fold button's chevron turns over. Open
  and folded are one markup, so no icon or row moves. A page load never animates: a kept fold is
  drawn folded. Below 900px the drawer is never folded; it slides in and out with a fading scrim.
  The Ask page, like the Graph page,
  fills the height under the top bar (a bleed page).
- **Past chats** (`ChatList`) are a column left of the lanes, with New chat at its top; below
  1400px they sit above the lanes as a short scrolling strip. "Hide past chats" folds the column
  (kept in `citadel-ask-history`); folded, "Show past chats" and New chat move into the page head.
  `?thread=<id>` opens a saved chat and scrolls its last lane to the top.
- **How it answered** (`TurnTimeline`) sits folded under each lane's answer: the ledger already
  shows the work while it happens, so the timeline never opens by itself here.

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
| `Dialog`     | Confirm destructive or blocking actions, or a short task that keeps the page behind it (add a company). The confirming action is last and named for what it does. `initialFocus` puts focus in the first field; `placement="top"` pins the top edge of a dialog whose body grows while you type. |
| `Stat`       | A count with its label, inside a `<dl>`. For summaries, not decoration.                        |
| `EmptyState` | Says what will appear and how to get it, with one action.                                      |
| `CitedAnswer`, `GraphPath` | The answer pattern from section 1. Citation chips link to the numbered source.   |
| `GraphWalk`  | The agent's walk for one answer (Ask page, direction D). Nodes are pills with their type dot; the start node is ink at the centre. Links are `--graph-edge` hairlines labelled `step · RELATIONSHIP` in mono; a link the rows only imply is dashed (the legend says so). The newest step of a running answer is accent (ring on its nodes, accent links); a lit citation is accent and everything else drops to 25% (links 20%). Above 12 nodes of its own, only the start, cited, lit and newest nodes keep their names; the rest are dots that name themselves on hover or focus. Carried nodes never crowd the walk: they keep their names only while the whole walk, carried nodes included, has 12 nodes or fewer. Earlier nodes drift at most 36 stage units when a step lands, and glide there with their links (`--duration-slow`); new links draw on from their ends. `carried` is context from earlier questions: its nodes and links are dashed and faint until a step touches them. Rules in `src/lib/walk.ts`. |
| `WalkSteps`  | The tool calls behind an answer: number circle (success tint; accent while running; danger with an alert icon when failed), the call in mono, rows and ms. One step opens to show its rows (paths as chains); rows a citation used carry its chip. The last row is the answer check, and a rejected check stays visible with the reason. |
| `WalkLedger` | The brain's work for one answer, one row per graph step in plain words ("Read recent work on Auth"). Each row has a mark for how it ended (done, running, found nothing, failed, not run), its rows and its time. Once the answer is in, repeated calls of one tool fold into one row; a call that found nothing or failed keeps its own row and says so under it. An open row shows its call and rows (`StepRows`). Hovering or focusing a row lights what its steps added to the walk; leaving the list, or the answer landing, clears it. The last row is the newest answer check ("Checked: every citation came from a step above"); a rejected check says why, and a pass after send-backs says how many ("Checked after 1 send-back: …"). There is no Checked, Assumed or Not in the brain footer. |
| `StepRows`   | The rows one step returned: paths as chains of nodes and relationships, other rows on one line. Rows a citation used carry its number; the active citation tints its rows. Says so when the step found nothing. |
| `Splitter`   | The line between two panes that resizes the one after it (rules in section 6, The Ask page). A hairline at rest; on hover, focus or drag it thickens to accent and shows a grip. A `separator` with `aria-valuenow`, so it is keyboard and screen reader usable. The parent places it full height and keeps `size` and `folded`; a fold by drag keeps the size from before the drag. |
| `AskLane`    | One question and everything it led to (section 6, The Ask page): strip, conversation with its ledger and answer, and its own walk. The page owns the columns (`walkWidth`), the splitter and the scrolling. Hovering a citation or a ledger row lights what backs it in the walk; a citation wins. The walk is drawn once and kept (folding only hides it). |
| `WalkAnswer` | The answer on the Ask page: limited Markdown rendered as text, citation chips that are buttons (hover or focus lights the path, click pins it), sources that say which step found them. No answer says why (refused, stopped, step limit). |
| `AnswerRating` | A thumbs up and down under an Ask answer, saved on its trace. Ghost icon buttons with `aria-pressed`; pressed is a filled ink icon on the sunken fill plus a line of words ("Marked right"), never accent (the citations own it). Pressing again takes it back. A thumbs down offers an optional note, which becomes the `why` of a draft eval case. Saving and a failed save are said in words; a failed save keeps the earlier thumbs. Hidden when the answer has no trace or was stopped. |
| `ModelPicker` | The Claude model for the next Ask question (direction P): a small outlined chip under the question field, left of Ask, with a chip icon and the model's name. It opens upward to the list: each model with a check when picked (the picked row also has the accent-soft fill), its name in the label width, a "Default" tag on the server's default and a warning-tinted "Slow" tag on a model that can take minutes, one muted line on what it is good for, and its price per token next to the cheapest in mono (x1, x20, x40, x100). The pick is per question and kept in the browser. While an answer runs the chip is dashed, muted and shows a padlock, and its name says why. Each answer then says "Answered by" with the model in a mono stamp; a follow-up on another model says it switched. |
| `ChatList` | The Ask page's past chats, newest first, in a column left of the thread (above it below 1400px). Each row is a link: the first question on one line, then "n questions · 5 min ago". The open chat has the surface fill and a hairline; a chat still answering shows a spinner and "answering", a failed one says "failed" in danger text, a stopped one says "stopped". Delete is a ghost icon shown on hover or focus (always on touch) and asks once inline (Delete / Keep). Shared per company: there are no users. |
| `TurnTimeline` | How one answer came about (on the Ask page, folded under the lane's answer): one summary line ("How it answered · 3 responses · 5 tool calls · 17,340 tokens") on the sunken fill that folds open (its `running` prop opens it while an answer runs; the Ask page leaves it folded). Inside, each Claude response is a hairline-ruled block: model, ms and stop reason in meta, its reasoning folded, its text, then every tool call as a row: status icon (success, danger, spinner), a badge for where it ran (Graph tool, Answer check, Server tool neutral; MCP with the server name in accent), the call in mono and its rows count or status. MCP and server calls fold open to their result. |
| `EntityRow`, `WorkItemRow`, `ActivityBars` | List and comparison patterns for people, teams, systems and work items. |
| `CompanyForm` | The fields of a company file for one wizard step or all three (Settings). Edits the draft; the page validates and hands back `errors`, which show under the field their `loc` names. Errors no field shows are listed at the foot of the step, so nothing blocks without a reason. Rules in `src/lib/onboarding.ts`. |
| `SourceCard` | One source of a company. GitHub: repository, what to read, token note with "Check again", GitHub's answer; an error only when the repository is private while the data is not `own`. Not found, rate limits and outages are warnings with "Check again", never blockers; Continue waits while a check is unanswered. Linear: workspace (`linear.app/` prefix; a pasted address is cut to its key) and team keys (put in capitals; none means every team), a hint naming `LINEAR_API_KEY`; a danger banner while the data is `public` (the build refuses it), which also shuts Continue and Save. The API's pattern errors show as sentences under their field, the bad team keys named once; an empty workspace shows none (the footer asks for it). Folders: one path. In "Add a source" a kind the data permission rules out (Linear under `public`) stays visible but off, its reason in text beside the row. |
| `ConfigPreview` | The YAML the server will write, with the top-level keys of the current step marked (bar, tint and a line of words). Shows the last valid text while the form has errors, and says so. |
| `BuildProgress` | One build: "Step n of N" from the plan, an ink progress meter (the one accent block of the view is the primary button), a table with a cell per source and stage, and the plain log. Each cell is icon plus word plus count or message; a skipped source is one merged cell saying why. Rules live in `src/lib/buildProgress.ts`. |
| `AddCompanyDialog` | Add a company from one public GitHub repository: one field (a link or `owner/name`), then what Citadel will make (company, graph, window). Private repos are refused in the field's error; no token, GitHub down and a company that already reads the repo or its owner are banners with their one action. "Advanced setup" opens the step-by-step form at `/new`. Rules in `src/lib/addCompany.svelte.ts`. |
| `CompanyRail` | One tile per company brain; one click switches company and keeps the section you are on. Monogram 15px at width 118; ink for the current tile (section 3). Tooltip shows the name and `brain_<slug>` in mono. The + opens `AddCompanyDialog`. |
| `TerritoryMap` | The whole company graph as territories (section 6, The graph map). Canvas plus an HTML label layer; drag pans, scroll zooms (`scrollZoom={false}` where it sits in a scrolling page; pinch and the buttons still zoom), click selects. Colours are read from the tokens and re-read when the theme changes. With `trail` (and `here`) it draws an agent's run over the map (section 6, The Systems page). |
| `AgentRun` | One agent run in the Systems page's rail: who and when, the question, a status (Working now in ink, Done, Stopped, Failed in danger), "n steps · m not on the map", then every step numbered as on the map, its tool and rows. Links to the chat an Ask run came from. |
| `NodeInspector` | The selected node: kind, territory and state, its fields (`get_entity`), where its neighbours live, its links by relationship, and its most linked neighbours, which select in turn. Counts come from the links the map draws. "Open on GitHub" only when the node has a url. |
| `AppShell`, `Sidebar`, `Topbar`, `ThemeToggle` | The frame. Nav items for unbuilt sections stay visible, inert, marked "Soon". The sidebar folds to icons (`--sidebar-folded`) from the top bar's fold button or the `[` key; the choice is kept in `citadel-sidebar`. `/graph`, `/ask` and `/systems` are bleed pages: no width cap, no padding. |

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
  `prefers-reduced-motion`. `--duration-slow` (320ms) is for motion that shows where something
  came from in a walk: a link drawing on from its ends and a node gliding to its new place (with
  its links). The scroll to a new question is the browser's native smooth scroll, not a token.
- Micro-interactions in the frame are `--duration-fast`: hover fills and colours fade, pressed
  controls give a little (`scale(0.97)` for sidebar items, `0.94` for rail tiles, `0.92` for the
  fold button), tooltips fade in a few pixels from their trigger, and the drawer's scrim fades in.
  The press is dropped under reduced motion.

## 9. Writing

- Name things by what the user knows: "Sync now", "Open graph", "Company graph".
- Buttons are verbs that say what happens, and the result uses the same word ("Delete graph",
  then "Graph deleted").
- Errors say what went wrong and what to do: "Use lowercase letters, digits and underscores only, like acme_labs".
- Empty states invite the next step instead of describing emptiness.
- Dates in tables and meta lines: `6 Feb`; with a year when it is not this year.

## 10. Theme

The theme follows the OS by default. `ThemeToggle` pins light or dark by setting
`<html data-theme>` and stores it in `localStorage` (`citadel-theme`). `app.html` applies the
stored value before first paint. Both themes are designed, not inverted: check every change in
both.
