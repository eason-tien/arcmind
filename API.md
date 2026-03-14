# 📡 ArcMind API Reference

Base URL: `http://localhost:8100`

All endpoints require `Authorization: Bearer <ARCMIND_API_KEY>` header unless noted.

---

## Core

### `GET /health`
Health check (no auth required).

```bash
curl http://localhost:8100/health
```

### `GET /healthz`
Kubernetes-style health probe (no auth required).

### `GET /v1/models`
List available LLM models and their providers.

### `POST /v1/models/default`
Set the default LLM model.

```json
{ "model": "gpt-4o", "provider": "openai" }
```

---

## Chat

### `POST /v1/chat`
Send a message to ArcMind.

```bash
curl -X POST http://localhost:8100/v1/chat \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Search for latest AI news"}'
```

**SSE streaming**: Response streams via Server-Sent Events.

---

## Cron Scheduling

### `GET /v1/cron/`
List all scheduled tasks.

### `POST /v1/cron/`
Create a new scheduled task.

```json
{
  "name": "daily_report",
  "cron_expression": "0 21 * * *",
  "command": "Generate daily summary report",
  "timezone": "Asia/Taipei"
}
```

### `DELETE /v1/cron/{name}`
Delete a scheduled task.

### `POST /v1/cron/{name}/trigger`
Manually trigger a scheduled task.

### `POST /v1/cron/{name}/pause`
Pause a scheduled task.

### `POST /v1/cron/{name}/resume`
Resume a paused task.

---

## Iterations (Shadow Staging)

### `GET /iterations`
List all iterations.

### `GET /iterations/{id}`
Get iteration details.

### `POST /iterations`
Create a new iteration.

### `POST /iterations/{id}/start`
Start an iteration.

### `POST /iterations/{id}/complete`
Mark iteration as complete.

### `GET /iterations/stats/summary`
Get iteration statistics.

---

## Projects

### `GET /api/projects`
List all projects.

### `POST /api/projects`
Create a new project.

### `GET /api/projects/{id}`
Get project details.

### `PUT /api/projects/{id}`
Update a project.

### `POST /api/projects/{id}/transition`
Transition project state.

---

## Tasks

### `GET /api/tasks/active`
List active tasks.

---

## Webhooks

### `POST /v1/webhook/{source}`
Receive webhook events from external services (N8N, Zapier, etc.).

---

## Federation (A2A)

### `POST /federation/task`
Receive federated task from another agent.

### `POST /federation/result`
Receive federated task result.

### `GET /federation/capabilities`
List agent capabilities for federation.

---

## Escalation

### `GET /v1/pm/escalations`
List escalated tasks.

### `POST /v1/pm/escalations/{task_id}/resolve`
Resolve an escalated task.

---

## Auto-generated Docs

FastAPI auto-generates interactive API docs:

- **Swagger UI**: `http://localhost:8100/docs`
- **ReDoc**: `http://localhost:8100/redoc`
