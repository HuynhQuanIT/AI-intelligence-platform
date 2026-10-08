# AI Intelligence Platform

Runnable starter application: **React + ASP.NET Core 8 + Python FastAPI/LangGraph + PostgreSQL/pgvector + Redis + MinIO**.

## Requirements
- Docker Desktop with Docker Compose v2
- 4 GB+ free memory recommended
- Ports 5173, 5000, 8000, 5432, 6379, 9000 and 9001 available

## Run
Windows PowerShell:
```powershell
Copy-Item .env.example .env
docker compose up --build
```
macOS/Linux:
```bash
cp .env.example .env
docker compose up --build
```

Open: frontend http://localhost:5173 · ASP.NET Swagger http://localhost:5000/swagger · AI docs http://localhost:8000/docs · MinIO http://localhost:9001 (platform / minio_dev_password).

Default `LLM_PROVIDER=mock` lets you exercise the workflow without a key; it is **not real model inference**. For OpenAI, set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in `.env`, then run `docker compose up -d --build ai-service`. Never commit `.env` or use development credentials in production.

## Operations
```bash
docker compose ps
docker compose logs -f frontend backend ai-service
docker compose down
```
Destructive reset: `docker compose down -v`.

## Included in this baseline
- Dashboard, Agent Studio, Knowledge Center, AI Playground, model configuration, cost metrics, traces, and security scan UI
- LangGraph agent pipeline with conditional routing and tool calling: Supervisor classifies the request, Security Agent blocks prompt injection before the model is called, Analysis Agent filters suspicious retrieved context
- Document ingestion from pasted text or uploaded PDF/DOCX/TXT/MD (original kept in a Docker volume; S3-compatible storage optional), paragraph-aware chunking
- Hybrid retrieval: keyword + Gemini embeddings in pgvector, fused with weighted Reciprocal Rank Fusion (falls back to keyword search when embeddings are unavailable)
- Conversations saved in PostgreSQL (list, reopen, delete) and answers streamed over Server-Sent Events
- Chat/model adapter and request/token/cost/latency logging
- Per-step traces and heuristic prompt-injection pattern detection

## Project structure
```
ai-service/app/
  main.py          # builds the FastAPI app and mounts the routers (entry point: app.main:app)
  schemas.py       # Pydantic request models shared by api and services
                   # (core/ also holds settings, passwords (scrypt) and tokens (JWT, OTP HMAC); services/auth.py: users, OTP, sessions)
  api/             # HTTP layer only: routers (chat, conversations, documents, monitoring, security, health)
  services/        # business logic used by routers: chat flow, telemetry (cost/logs), conversations
  agents/          # LangGraph pipeline (graph.py), Tool Agent tools (tools.py), prompt-injection scan (security.py)
  rag/             # text normalisation, chunking, extraction, embeddings, storage, documents, retrieval
  llm/             # model adapters (mock / OpenAI-compatible / Gemini) and streaming
  core/            # infrastructure shared by all layers (database pool)
ai-service/tests/  # mirrors app/: tests/<package>/test_<module>.py
backend/AIPlatform.Api/   # ASP.NET gateway (forwards /api/platform/* to ai-service)
  Program.cs       # wiring only
  Endpoints/       # one file per area: Chat, Conversation, Document, Monitoring, Security, Health
  Services/        # AiProxy: relays requests/responses to ai-service
  Models/          # request models
  Extensions/      # service registration (HttpClient "ai", CORS)
frontend/src/      # React + Vite
  App.tsx          # shell: sidebar, header, error banner, page switch
  pages/           # one component per page (Dashboard, KnowledgeCenter, Playground, ...)
  components/      # reusable UI (Panel, Stat, TraceTable, Sidebar, Markdown)
  hooks/           # usePlatformData (shared metrics/docs/traces), useChat (conversations + SSE)
  api/             # client.ts (fetch wrapper), sse.ts (SSE reader)
  config/          # navigation and page descriptions
  types.ts         # shared types
infra/postgres/    # SQL init
```
Dependency direction: `api -> services -> agents -> rag/llm -> core`. Lower layers never import upper ones.

Test naming: `tests/<package>/test_<module>.py` tests one module (`tests/rag/test_chunking.py` -> `app/rag/chunking.py`). Tests of a whole endpoint are named after the router (`tests/api/test_chat.py`, `test_chat_stream.py`) and carry the `integration` marker when they need PostgreSQL.

## Authentication and roles
Sign-in is email + password. OTP by email is used only to verify an email when registering and to reset a forgotten password.

| Feature | admin | user |
|---|---|---|
| Chat (own private conversations) | yes | yes |
| Knowledge Center (read, download) | yes | yes |
| Upload / delete / reindex documents | yes | no |
| Agent Studio, Dashboard, traces, metrics, Security Center | yes | no |
| User management (approve, deactivate, change role) | yes | no |

1. Set `JWT_SECRET` (>= 32 random chars), `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`; the first admin is created at startup. Without a valid `JWT_SECRET` the service refuses to start.
2. `REGISTRATION_MODE` decides who may self-register: `approval` (default, admin must approve), `domain`, `open` or `closed`.
3. OTP mail: `MAIL_BACKEND=console` prints the code in the ai-service log (local testing only); `smtp` sends real mail (Gmail needs 2-step verification and an App Password; use a dedicated mail service for production).
4. Security: scrypt password hashes (>= 10 chars); OTP stored as HMAC, 6 digits, 5 minutes, single use, 5 attempts, resend every 60 s (3 per 10 min, per email and per IP); 5 wrong passwords lock the account for 15 min; the JWT lasts 60 min and is re-checked against the database on every request, so deactivating a user, changing a role or resetting a password logs old sessions out immediately; login and reset errors never reveal whether an email exists.
5. Existing conversations are assigned to the first admin. The document store is shared by everyone who can sign in, so keep `REGISTRATION_MODE=approval` (or `domain`) if documents are sensitive.
6. Limits: the chat rate limit and IP login throttling are kept in memory (reset on restart, not shared between instances; move to Redis before scaling out); lockout and OTP state live in PostgreSQL. The JWT is kept in the browser's `localStorage`; there is no refresh token (sign in again after 60 min). One organisation per deployment.
7. ai-service trusts the `X-Real-IP` set by nginx for per-IP limits, so do not expose ai-service or the gateway port directly to the internet. Compose publishes ai-service on 127.0.0.1 only.

## Tests
```bash
cd ai-service
pip install -r requirements-dev.txt
pytest                      # unit tests; integration tests are skipped when PostgreSQL is unreachable
DATABASE_URL=postgresql://platform:platform_dev_password@localhost:5432/aiplatform pytest   # with PostgreSQL (docker compose up -d postgres)
```
CI (`.github/workflows/ci.yml`) runs pytest against PostgreSQL + pgvector, type-checks and builds the frontend, builds the ASP.NET gateway and validates `docker-compose.yml`. The tests never call a real LLM (`LLM_PROVIDER=mock`, plus a fake Gemini client for streaming). Retrieval thresholds are locked with the real similarities measured on 04/10/2026; re-measure and update `tests/rag/test_retrieval.py` when the thresholds or embedding model change.

## Known limitations / production work
- The Tool Agent (Gemini function calling) can call four read-only tools (list/search/read documents, calculator), enabled per tool in the `agent_tools` table; tool output passes through the Security Agent. Retries, write actions, and human approval are not implemented.
- Embeddings need `LLM_PROVIDER=gemini`; document text is sent to Google's API to create vectors.
- Scanned (image-only) PDFs are rejected: there is no OCR.
- Streaming: Gemini text streams chunk by chunk; blocked replies and Tool Agent answers arrive in one piece.
- Redis is provisioned but not yet used for caching.
- MinIO is optional (`--profile s3`, `STORAGE_BACKEND=s3`): its images were removed from Docker Hub and the quay.io tags are no longer reliably pullable, so uploads default to a local volume.
- Prompt-injection scanning is a small pattern list, not a security guarantee.
- Cost uses illustrative token rates, not provider billing.
- Authentication, RBAC, tenant isolation, rate limits, TLS, secrets management, backups, malware scanning, and production observability are not implemented.

Architecture: `Browser → Nginx/React → ASP.NET Core API → FastAPI/LangGraph → PostgreSQL`. Browser requests go through the ASP.NET `/api/platform/*` proxy.