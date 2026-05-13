# SMART-GoT (lean prototype)

A minimal research prototype for SMART goal decomposition into workstreams, served through a
FastAPI backend and Next.js web app.

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pnpm install
export OPENAI_API_KEY=your-token
```

You can also put `OPENAI_API_KEY=...` in the repo-root `.env` or `.env.local`. The FastAPI
sidecar now loads those files on startup and does not override already-exported shell values.

## Local development

Start the API and web app together from the repo root:

```bash
pnpm dev
```

This runs:

- FastAPI on `http://127.0.0.1:8001`
- Next.js on `http://127.0.0.1:3000`

Set `NEXT_PUBLIC_SMARTGOT_API` if the web app should talk to a different API origin.
Generation endpoints require `OPENAI_API_KEY`. Without it, graph generation and planning fail with a clear API error instead of using mock content.

## API bootstrap

Create a graph with the API instead of a CLI command:

```bash
curl -X POST http://127.0.0.1:8001/api/v1/graph/init \
  -H 'Content-Type: application/json' \
  -d '{"path":"out/graph.json","goal":"Plan a 10k charity run","overwrite":true}'
```

## Core staged workflow endpoints

- `POST /api/v1/graph/init`
- `GET /api/v1/graph`
- `GET /api/v1/baseline/questions`
- `POST /api/v1/jobs/layer-build`
- `POST /api/v1/focus`
- `POST /api/v1/jobs/plan-generate`
- `POST /api/v1/jobs/plan-replace`
- `POST /api/v1/jobs/task-toggle`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`

## Validation

```bash
python -m pytest -q
pnpm lint
pnpm typecheck
pnpm build
```
