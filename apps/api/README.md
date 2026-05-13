# SMART-GoT Sidecar API

Run directly:

```bash
export OPENAI_API_KEY=your-token
uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8001
```

Recommended repo workflow:

```bash
export OPENAI_API_KEY=your-token
pnpm dev
```

Generation endpoints require `OPENAI_API_KEY`. If the token is missing, generation requests fail explicitly instead of falling back to mock output.

Bootstrap a graph:

```bash
curl -X POST http://127.0.0.1:8001/api/v1/graph/init \
  -H 'Content-Type: application/json' \
  -d '{"path":"out/graph.json","goal":"Plan a 10k charity run","overwrite":true}'
```

Primary staged endpoints:

- `GET /api/v1/graph`
- `GET /api/v1/baseline/questions`
- `POST /api/v1/jobs/layer-build`
- `POST /api/v1/focus`
- `POST /api/v1/jobs/plan-generate`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
