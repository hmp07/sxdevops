# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SxDevOps is an open-source AIOps agent platform — Vue 3 frontend + Django backend — that integrates observability, event center, task automation, CMDB, container management, and RBAC into AI-agent-callable workflows. Licensed under Apache 2.0.

## Development Commands

### Backend (Django)

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate                  # apply migrations
python manage.py seed_data                # seed demo data (users, hosts, tasks)
python manage.py seed_templates           # seed AI agent & task templates
python -m daphne -b 0.0.0.0 -p 8000 sxdevops.asgi:application
```

Backend tests:
```bash
cd backend && python manage.py test       # all tests
cd backend && python manage.py test ops   # single app
```

### Frontend (Vue 3 + Vite)

```bash
cd frontend
npm install
npm run dev       # dev server on port 3000, proxies /api → localhost:8000
npm run build     # production build to dist/
```

### Docker Compose

```bash
docker compose up -d --build    # app (port 8000) + MySQL 8 + Redis 7
docker compose down
```

The container auto-runs `migrate`, `seed_data`, and `seed_templates` on first start. Set `SXDEVOPS_SEED_DATA=0` to skip.

## Architecture

### Backend (Django 5.x, ASGI via Daphne + Channels)

Django project at `backend/sxdevops/` with 9 apps:

| App | Responsibility |
|-----|---------------|
| `ops/` | Core: tasks, hosts, deployments, alerts, K8s/Docker, logs, metrics, tracing, WebSocket consumers, Zabbix client |
| `aiops/` | AI agent engine: chat sessions, knowledge graph, MCP servers, Skills, model providers, audit |
| `cmdb/` | Configuration management: CI types, config items, topology, iTop sync, device matching |
| `eventwall/` | Event center: event records, sources, analysis |
| `rbac/` | Permissions, roles, groups, module settings — `registry.py` is the source of truth for permission codes |
| `sqlaudit/` | SQL audit: connects to user-managed external databases, NOT the platform's own DB |
| `marketplace/` | Service templates and deployments |
| `iac/` | Infrastructure as Code (Terraform) |
| `multicloud/` | Multi-cloud resource management |

**Key patterns:**
- Database engine is selected via `DATABASE_ENGINE` env var or `config.json` → `settings.py:_build_database_config()` resolves to sqlite/mysql. Default is SQLite (`backend/db.sqlite3`).
- All DB queries use Django ORM — zero raw SQL in migrations (113 files, no `RunSQL`), only one `cursor.execute` in `seed_data.py`.
- ASGI middleware (`asgi_middleware.py`) monkey-patches DRF Response for Daphne compatibility.
- RBAC enforcement lives in backend (`rbac/registry.py`, `rbac/permissions.py`); frontend hiding is only a mirror.
- WebSocket routing in `ops/routing.py`, consumed by Daphne ASGI.

### Frontend (Vue 3 + Element Plus + Pinia)

Entry: `frontend/src/main.js` → Pinia → Router → Element Plus (zhCn locale) → mount.

```
src/
├── views/          # 54 page components (PascalCase)
├── layout/         # AppLayout.vue — sidebar + header + router-view + AIOpsChatWidget
├── router/         # index.js — 540 lines, RBAC guards via beforeEach
├── stores/         # auth.js (token, user, permissions), app.js (sidebar state)
├── api/
│   ├── request.js  # Axios instance — /api base, Token auth, response interceptor strips .data
│   └── modules/    # aiops.js, cmdb.js, container.js, eventwall.js, ops.js, rbac.js, sqlaudit.js
├── components/     # Reusable: AIOpsChatWidget, CmdbTopologyCanvas, EventWallTabs, TaskResourceBase
├── composables/    # useRouteTabState.js
└── utils/          # permission.js, taskDraftTitle.js, workorderFlows.js
```

**Key patterns:**
- Axios interceptor in `request.js` extracts `response.data` — components receive the inner data directly, NOT `{ data: ... }`. Multiple bugs have been caused by double-unwrapping.
- Route permissions use `meta.permission` (single) or `meta.anyPermissions` (array). Dynamic redirects route users to their first permitted page.
- RBAC: `authStore.hasPermission(code)`, `hasAnyPermission(codes)`, `hasAllPermissions(codes)` — superusers bypass all checks.
- Element Plus icons are globally registered — no need to import per-component.

### Agent Workflow (backend/aiops/)

The AIOps agent pipeline is:

```
User input → Action Router (classify task type & risk)
          → Agent Mode (Direct | ReAct | Plan+ReAct)
          → Preflight (RBAC, risk check, missing params, dependency check)
          → Skill/SOP (domain capability packages with output contracts)
          → MCP/Tool Registry (tools = Skill deps ∩ MCP availability ∩ RBAC ∩ Action policy)
          → Structured Facts (logs, metrics, traces, alerts, events)
          → Two-Phase Answer (conclusion, evidence, risks, suggested actions)
          → Pending Action (writes/executions must be confirmed)
          → Platform API execution → Audit trail
```

Key files: `aiops/services.py` (orchestration), `aiops/knowledge_graph.py` (topology), `aiops/action_handlers.py` (handler registry).

### Docker Deployment

Multi-stage build (`Dockerfile`): `node:20-alpine` builds frontend, `python:3.12-slim` runs backend. Entrypoint (`docker/entrypoint.sh`) waits for DB via TCP socket, then conditionally migrates and seeds.

## Coding Conventions

- **Python**: 4-space indent, snake_case modules and helpers.
- **Vue**: Views/Layout use PascalCase filenames (`K8sManage.vue`). API modules, stores, utils use lowercase.
- **No linter/formatter is committed** — match surrounding style and remove unused imports.
- **Chinese text**: Must be UTF-8. Avoid mojibake from terminal encoding mismatches.

## UI Convention (Feishu-Style Workbench)

For management/console pages, follow the existing pattern:
- Compact top hero with single-row title.
- `hero + stats cards + compact hint strip + tabs/content` flow.
- Reuse `release-stat-card` visual language for top metrics.
- Filters (env, cluster, namespace, domain) go in compact toolbars near tabs.
- Avoid old `page-header` blocks and oversized marketing-style sections in operational pages.

Reference pages: `TaskWorkbench.vue`, `Deployments.vue`, `K8sManage.vue`, `ContainerManage.vue`.

## RBAC Convention

1. Define permissions in `backend/rbac/registry.py` first.
2. Backend views check permissions — frontend is just UX mirroring.
3. Add route guards in `frontend/src/router/index.js` (`meta.permission` or `meta.anyPermissions`).
4. Add menu items in `frontend/src/layout/AppLayout.vue` with `canAccess()` checks.
5. For new apps, register in `backend/sxdevops/urls.py` and `backend/sxdevops/settings.py` INSTALLED_APPS.

## External Integrations

- **Observability**: Prometheus, Grafana, SkyWalking, Tempo, Jaeger, Zipkin, Loki, ELK, Aliyun SLS
- **Automation**: Kubernetes API, Docker, SSH
- **CMDB**: iTop REST API
- **Monitoring**: Zabbix 7.x API
- **Cloud SDKs**: Aliyun ECS, Huawei Cloud ECS
- **MCP**: Go-based iTop MCP server in `tools/itop-mcp-server/`

Configuration for Zabbix and iTop lives in `backend/sxdevops/settings.py` (ZABBIX_CONFIG, ITOP_CONFIG).

## Database Notes

- Dev default: SQLite at `backend/db.sqlite3`
- Docker/production: MySQL 8 via `config.json` or env vars
- Adding PostgreSQL: requires only adding a `_postgresql_database_config()` function in `settings.py`, adding `psycopg[binary]` to `requirements.txt`, and updating `docker-compose.yml`. Zero model or migration changes needed — all 113 migrations use pure Django ORM.
- `sqlaudit/` connects to external user databases with `pymysql` — it is independent of the platform's own database choice.

## Documentation

- `README.md` — project overview, quick start, screenshots (Chinese)
- `AGENTS.md` — repository guidelines for AI assistants
- `docs/` — architecture design docs (Chinese), screenshots
- `docs/AIOps2.0升级优化方案.md` — AIOps 2.0 upgrade design
- `docs/Zabbix-iTop集成实施计划.md` — Zabbix/iTop integration plan
