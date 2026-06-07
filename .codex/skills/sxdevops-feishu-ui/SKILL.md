---
name: sxdevops-feishu-ui
description: Use for any new frontend page or UI adjustment in this repository when the user does not explicitly request a different style. Applies the repo's default Feishu minimal premium workbench style based on TaskWorkbench task history and Deployments pages, including hero, tabs, metric cards, filter bars, lists, buttons, and compact vertical spacing.
---

# SXDevOps Feishu UI

## Use When

- Building a new page under `frontend/src/views/`.
- Restyling or aligning an existing frontend page, embedded management panel, or console view.
- The user asks to "对齐 UI", "优化页面样式", "按当前项目风格来", or similar.
- The user does not explicitly ask for a different visual direction.

If the user explicitly asks for another style, follow the user.

## Source Of Truth

Use these pages before introducing any new UI pattern:

1. `frontend/src/views/Deployments.vue`
2. `frontend/src/views/TaskWorkbench.vue`
3. `frontend/src/components/cmdb/CmdbHostTaskCenter.vue`
4. `frontend/src/views/SqlAudit.vue`
5. `frontend/src/views/K8sManage.vue`
6. `frontend/src/views/ContainerManage.vue`

Read `references/ui-benchmarks.md` when you need the exact class patterns and spacing values.

## Default Style

- Overall tone: Feishu-like minimal premium workbench UI.
- Use bright white and blue-gray surfaces, restrained blue emphasis, soft borders, and low-noise shadows.
- Prefer existing repo structures over inventing a new composition.
- Use `workbench-page-shell` for full pages when the page is console or management oriented.
- Do not use the old `page-header` pattern for new or restyled pages.
- Do not add hero buttons unless the user explicitly asks.
- Do not keep platform reminder strips by default.
- Do not duplicate stats inside list cards when the page already has a top stats row.
- Keep actions on the same row as the list title, not inside the hero.

## Layout Rules

### Hero

- Use a top `hero panel`.
- Keep one title row: icon + `h2` + concise inline subtitle.
- Reuse the same visual language as `Deployments.vue` and `TaskWorkbench.vue`:
  - panel padding `14px 16px`
  - hero radius follows `Deployments.vue`: component-local `.hero.panel { border-radius: 20px; }`
  - hero gradient `linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%)`
  - hero border color `rgba(36,91,219,.09)`
  - header icon `42px * 42px`, pale blue background, blue foreground
- Hero bottom margin stays at `0`.
- For management pages that use top metrics, keep the page order as `hero -> stats cards -> tabs (if any) -> list/content`.
- Do not add stronger page-specific selectors such as `section.hero.panel... !important` for hero radius unless the benchmark page already does it; match the application release page's cascade and selector shape.
- If a page defines a generic `.panel` radius, still add the same final `.hero.panel { border-radius: 20px; }` rule used by `Deployments.vue`.

### Tabs

- Main tabs use the repo's blue pill workbench style.
- Prefer `neo-tabs theme-blue`.
- Outer tabs shell:
  - padding `3px`
  - border radius `12px`
  - soft gray border
- Main tab button:
  - height about `38px`
  - compact horizontal padding
  - `13px` bold or semibold text
  - translucent blue active state
- Secondary tabs should sit directly above the filter area with a tighter gap than a normal section break.
- Keep the tabs shell immediately below the stats row when both are present, not above it.
- Active tabs should use a pale transparent blue fill such as `rgba(51, 112, 255, 0.1)` or `#e8f0ff` with blue text; do not use the global solid/gradient blue active style on workbench management pages.

### Stats Cards

- Default to `audit-grid`.
- Default metric card shape:
  - `audit-card audit-card--inline`
  - min-height `68px`
  - padding `14px 16px`
  - radius `14px`
  - soft border and subtle shadow
- Use clickable cards (`audit-card--action`) when cards switch tab, filter, or list state.
- Use tone variants only when they carry meaning:
  - base
  - `audit-card--success`
  - `audit-card--warning`
  - `audit-card--danger`
- Standard typography:
  - label `13px`, semibold
  - value `24px`
- If the page matches task history style, the card can place label and value on one row, but it must keep the same height, border, shadow, and active state language.

### List And Content Card

- List-driven pages should use one `workbench-card` to wrap title, filter bar, and table.
- Header row uses:
  - `section-toolbar`
  - `toolbar-head`
  - `toolbar-title`
  - `toolbar-desc`
- Filter row uses:
  - `workbench-toolbar workbench-toolbar--history`
- Keep filter bar visually inside the card with its own outer border treatment.
- Prefer one list card instead of a separate filter card plus another list card.
- On desktop, keep dense filter rows in a single line when the page's normal working width allows it; prefer narrower controls and horizontal overflow over wrapping to a second line.
- For module visibility or feature-switch management pages, keep the page as `hero -> single workbench-card -> table/list`; do not add stats cards unless the user asks. Required rows should use disabled switches plus a compact "required" tag, while configurable rows use the actual switch control.

### Buttons

- Keep buttons compact.
- Primary buttons are for create, confirm, or high-priority actions only.
- Refresh and secondary actions should use the lighter workbench button treatment.
- Buttons belong in section headers or filter rows, not the hero.

### Tables

- Use Element Plus tables with restrained density.
- Keep header tone soft and readable.
- Avoid oversized row padding.
- Match the information density of TaskWorkbench history and Deployments instead of older spacious pages.

### Vertical Rhythm

- Page root vertical gap: `6px`.
- Stats row and tabs block should not introduce extra top or bottom margins.
- Section title row to filter row spacing should stay tight.
- Use the TaskWorkbench history / Deployments rhythm as the default baseline for new pages.
- Avoid adding extra vertical wrappers between hero, stats, tabs, and the content card unless the page absolutely needs them.

## Execution Checklist

1. Open the benchmark pages before making layout decisions.
2. Reuse repo class names and structural patterns where possible.
3. Align hero, tabs, stats cards, filter bar, list card, buttons, and spacing to the benchmark pages.
4. Remove redundant reminders or duplicated stats unless the user asks to preserve them.
5. Run `cd frontend && npm run build`.
6. If Chinese copy changed, confirm the file is still UTF-8 and readable.

## References

- `references/ui-benchmarks.md`
