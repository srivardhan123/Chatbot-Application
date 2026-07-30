# Lightweight LLM Inference Logging System

A production-ready chatbot application with comprehensive inference logging and monitoring. Built with Django + React, using Google Gemini as the LLM provider.

> **Core Focus**: Sensible schema design and practical tradeoffs.

## Overview

This system demonstrates a clean separation of concerns:
- **Frontend**: React chatbot UI (multi-turn conversations)
- **Backend API**: Django REST Framework with a lightweight SDK wrapper
- **Ingestion Pipeline**: Real-time inference metadata capture and storage
- **Database**: SQLite with normalized schema (Conversation → Message → InferenceLog)

### Core Features

✅ **Multi-turn chatbot** — maintains conversation context (last 20 messages)  
✅ **Inference logging** — captures model, provider, latency, token usage, status, errors, input/output previews  
✅ **Ingestion API** — real-time metadata ingestion with DRF validation  
✅ **Django admin** — free logs/conversations browser (no extra UI code needed)  
✅ **Error resilience** — logging failures never break the chat experience  

---

## Quick Start

### Prerequisites
- Python 3.9.6+ (or 3.8+)
- Node.js 18+ (via nvm recommended)
- Google AI Studio API key (free tier, no billing required)

### Backend Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env with your Gemini API key (never commit this)
cp .env.example .env
# Edit .env, set: GEMINI_API_KEY=<your-key-from-aistudio.google.com>

# Initialize database
python manage.py migrate

# (Optional) Create a superuser for /admin/ access
python manage.py createsuperuser

# Run dev server (default: http://127.0.0.1:8000)
python manage.py runserver 8000
```

### Frontend Setup

```bash
cd frontend
npm install

# Run dev server (default: http://localhost:5173)
npm run dev
```

### Access Points

| URL | Purpose |
|-----|---------|
| `http://localhost:5173` | Chat UI |
| `http://127.0.0.1:8000/api/conversations/` | Conversation CRUD |
| `http://127.0.0.1:8000/api/logs/` | Inference logs browser (JSON) |
| `http://127.0.0.1:8000/admin/` | Django admin (conversations, messages, logs) |

---

## Architecture Overview

**System Layers:**
- **Frontend** (React): Chat UI with sidebar, message display, input form
- **Backend API** (Django + DRF): REST endpoints for conversations, messages, logs
- **Database** (SQLite): Normalized schema (Conversation → Message → InferenceLog)
- **External LLM**: Google Gemini API

**Request Flow:**
1. User sends message via React UI
2. Django saves user message to DB immediately
3. Loads last 20 messages for context
4. Calls LoggedGeminiClient (SDK wrapper)
5. SDK captures metadata: latency, tokens, status, errors
6. SDK POSTs metadata to ingestion endpoint (`/api/logs/`)
7. Django saves assistant reply to DB
8. Frontend displays both messages

**Key Insight**: Logging is decoupled via HTTP POST, so logging failures never break the chat experience.

See **ARCHITECTURE.md** for detailed:
- Ingestion flow diagrams
- Logging strategy & failure modes
- Scaling considerations (10 req/s → 1000+ req/s)
- Error recovery flows
- Future: Event-driven ingestion (Kafka/Redis)

---

## Schema Design: Sensible Choices & Tradeoffs

### Table 1: Conversation

**Schema:**
```python
id: UUID (primary key)
title: str(max=255, default="New Conversation")
created_at: datetime (auto_now_add=True)
```

**Design Rationale:**

| Decision | Why | Alternative | Tradeoff |
|----------|-----|-------------|----------|
| **UUID instead of auto-increment int** | Globally unique, no sequence leakage, safe for public URLs | Auto-increment int (1, 2, 3...) | Slightly larger PK (16 bytes vs 8), but better security/privacy |
| **title field** | Users want to name their conversations for quick reference | No title, just timestamps | Extra storage (255 chars per row), but much better UX |
| **Single created_at, no updated_at** | Conversations are immutable after creation (only messages change) | Track updates | Simpler schema, less DB churn |

**Tradeoff Example**: UUID takes 16 bytes vs 4 for int32. For 1 million conversations, that's 12MB extra. Production would accept this; if space was critical, we'd use ULID (8 bytes, still unique) or hash the UUID to an int.

---

### Table 2: Message

**Schema:**
```python
id: int (primary key, auto-increment)
conversation_id: UUID (FK → Conversation, CASCADE)
role: enum("user" | "assistant")
content: TextField
created_at: datetime (auto_now_add=True)
```

**Design Rationale:**

| Decision | Why | Alternative | Tradeoff |
|----------|-----|-------------|----------|
| **int PK, not UUID** | Messages are immutable, sequential per conversation; int is lighter + humans rarely reference message IDs directly | UUID for each message | Saves 8 bytes per message; FK index on conversation_id is the main query path anyway |
| **ON DELETE CASCADE** | Messages are meaningless without a conversation; delete conversation = delete its messages | ON DELETE SET_NULL | Cleaner semantics; a message without a conversation is a dead row. Cascade is faster (no dangling FKs) |
| **role as enum, not FK** | Only 2 values ("user", "assistant"); enum saves space + clarity | Separate Role table (1-to-many) | 1 byte for enum vs 4+ for FK lookup; no need to join tables for a simple choice |
| **TextField, not max_length=X** | LLM replies can be arbitrarily long (don't truncate mid-sentence) | VARCHAR(5000) with truncation | PostgreSQL/MySQL optimize TextField fine; SQLite stores inline anyway. Avoid cutting off important text. |
| **No foreign key to InferenceLog** | Not every message triggers an LLM call (first message is just a user message). InferenceLog is optional/supplementary. | Bidirectional FK | Looser coupling; a log can exist without a message, and vice versa |

**Tradeoff Example**: `ON DELETE CASCADE` is aggressive. If a conversation is deleted by accident, all messages go with it. Alternative: `SET_NULL` + a cleanup job later. But CASCADE is standard practice; we're trusting Django ORM to only delete via `conversation.delete()`, not raw SQL.

---

### Table 3: InferenceLog

**Schema:**
```python
id: int (primary key)
conversation_id: UUID (FK → Conversation, SET_NULL, nullable)
session_id: str(64)
provider: str(64) # e.g., "google"
model: str(128) # e.g., "gemini-flash-latest"
latency_ms: float
input_tokens: int (nullable)
output_tokens: int (nullable)
status: enum("success" | "error")
error_message: TextField (nullable)
input_preview: TextField (blank=True)
output_preview: TextField (blank=True)
created_at: datetime (auto_now_add=True)
```

**Design Rationale:**

| Decision | Why | Alternative | Tradeoff |
|----------|-----|-------------|----------|
| **Nullable conversation_id + SET_NULL** | Logs are audit-trail artifacts; if a conversation is deleted, keep its logs for post-mortem analysis. | ON DELETE CASCADE | Allows logs to "survive" a conversation deletion; production compliance/debugging requirement. Trade off: orphaned logs clutter the table; need periodic cleanup jobs. |
| **session_id (not FK)** | Maps to conversation_id but stored as string; allows pre-logging before conversation is saved | FK to Conversation | Decouples logging from transaction success. If conversation save fails after LLM call, the log still exists (with session_id = would-be-conversation_id). |
| **input_tokens / output_tokens: nullable** | Some LLM APIs don't return token counts on error; capturing them as nullable avoids forcing dummy values | Default 0 or -1 | Nullable forces app logic to handle None; cleaner than magic numbers. Queries must use `IS NULL` not `= 0`. |
| **latency_ms always captured (even on error)** | Errors often have latency info (e.g., auth errors fast, timeouts slow); useful for debugging | Skip on errors | Always capturing reveals patterns: auth errors = 50-200ms, actual timeouts = 30000ms+. Helps distinguish failure modes. |
| **input_preview + output_preview (truncated to 200 chars)** | Full messages are in `Message` table; logs are for ops/monitoring (quick glance). Truncation saves space. | Store full text | 200 chars is usually enough to understand what the query/response was about. Full text ≈ 1-10KB per log; over 1 million logs that's 1-10GB. Tradeoff: readability vs storage. For production dashboards, 200 chars is fine; full text lives in Message table. |
| **status enum (not FK to Status table)** | Only "success" or "error"; no need to normalize further | Separate table | Enum is 1 byte, FK lookup is overhead. Standard Python/Django pattern for small fixed sets. |
| **error_message (TextField, nullable)** | Stores exception message for failed calls (e.g., "404 NOT_FOUND: model unavailable") | No error field | Invaluable for debugging; query all logs where status="error" to find patterns. Production systems live on error logs. |

**Tradeoff Example**: Nullable conversation_id + SET_NULL is risky. If a conversation is deleted, its logs become orphaned. Best practice: don't delete conversations in production (mark as archived instead), or run a cleanup job to delete old orphaned logs. We document this in the README's "Production Considerations."

---

## Practical Tradeoffs Summary

### 0. **Tech Stack: Google Gemini, Django, Python**

**Google Gemini over Claude/GPT-4/DeepSeek**: Gemini's free tier (via Google AI Studio) requires no billing setup—just an API key, no credit card needed. This is ideal for a demo/MVP where we want zero-friction onboarding. Claude and GPT-4 are pay-as-you-go from day one (even if cheap); DeepSeek is cheap but still requires payment. For a proof-of-concept, Gemini's "truly free" tier wins. **Tradeoff**: Gemini is good for demos but Claude/GPT-4 have better quality for production; we'd swap in production.

**Django over FastAPI**: The role JD specified Django as the backend framework. Django comes with batteries-included (ORM, migrations, built-in admin panel, auth). Beyond the JD requirement, Django's `/admin/` dashboard (zero code, automatic CRUD + filtering) saved significant time—equivalent to 20+ lines of custom UI code that we didn't have to write. FastAPI is lighter and more async-native, but it requires building ops tools from scratch. **Tradeoff**: FastAPI would be cleaner for a pure API-first service; Django is better when you need built-in admin + ORM out-of-the-box.

**Python over Node.js**: The role JD specified Python as the backend language. Beyond the JD requirement, Python's LLM SDK ecosystem (Anthropic, Google, OpenAI all have rich Python SDKs with better type hints and async patterns) makes building inference wrappers + ingestion pipelines significantly faster than Node.js equivalents. Django ORM is also more mature than TypeORM/Sequelize. **Tradeoff**: Node.js would let us use one language across frontend+backend (React JS); Python forces a language split. But Python's LLM tooling and Django ecosystem are stronger for this use case and aligned with the role requirements.

### 1. **SQLite vs PostgreSQL**
- **Choice**: SQLite (file-based, zero setup)
- **Why**: 5-6 hour MVP; Postgres requires server installation/management
- **Cost**: Single-user, sequential writes only; good for dev/demo, not production at scale
- **Swap**: Change `DATABASES` in settings + `DATABASE_URL` env var; schema is the same

### 2. **Message History: Replay vs Server-Side Sessions**
- **Choice**: Replay (resend full 20-message history with each request)
- **Why**: Stateless, aligns with real LLM APIs (GPT, Claude, Gemini all use this)
- **Cost**: Higher token usage as conversations grow; tokens scale with conversation length
- **Future**: Token-based truncation (use `tiktoken` to cut off at 2000 tokens instead of 20 messages)

### 3. **Hard Message Limit (20 msgs) vs Token-Based**
- **Choice**: Hard message count
- **Why**: Simple to reason about; doesn't need `tiktoken` dependency
- **Cost**: Misses context if messages are short; wastes tokens if messages are long
- **Example**: "yes" (1 token) × 20 msgs = 20 tokens context. "Here is a detailed explanation..." (100 tokens) × 20 msgs = 2000 tokens context. Same message count, wildly different token spend.

### 4. **HTTP POST Ingestion vs Direct Function Call**
- **Choice**: HTTP POST to local `/api/logs/` endpoint
- **Why**: Demonstrates the actual SDK → ingestion-service boundary; logging failures don't break chat
- **Cost**: Extra HTTP overhead (microseconds on localhost); more code to maintain
- **Benefit**: Future-proof; swap in Kafka/Redis Streams without touching the SDK

### 5. **Logging Failures Are Silent**
- **Choice**: `except requests.RequestException: pass` (swallow errors)
- **Why**: Logging is infra; user's chat should never break because logging is down
- **Cost**: Silent failure; if `/api/logs/` is down, users won't know (or see metrics/alerts elsewhere)
- **Production**: Emit metrics (prometheus/datadog) on failed logs; alert ops separately

### 6. **No Pre-Aggregated Metrics**
- **Choice**: Store raw `input_tokens`, `output_tokens`, `latency_ms` only
- **Why**: Avoid over-engineering for a demo; queries can aggregate on-the-fly
- **Cost**: Dashboard queries are slower (compute sum/avg at query time)
- **Future**: Separate analytics DB (ClickHouse, BigQuery) with pre-aggregated hourly/daily rollups

---

## Metadata Captured

✅ **All 12 critical metadata fields**:
- model, provider, latency, input/output tokens, timestamps
- request status/errors, conversation/session ID, input/output previews

See **ARCHITECTURE.md** for detailed schema design, ingestion flow diagrams, logging strategy, scaling considerations, and failure handling assumptions.

---

## Bonus Features Implemented

### ✅ Multi-Provider Support (Architecture + Mocking)
This project demonstrates a **provider-agnostic logging architecture** that works with multiple LLM vendors:

- **Google Gemini** — Real integration (free tier via Google AI Studio, no billing)
- **Anthropic Claude** — Mocked responses (demonstrates architecture; real calls require paid API key)
- **OpenAI GPT-4** — Mocked responses (demonstrates architecture; real calls require paid API key)

**Why mock Claude and GPT-4?** They have no free API tiers; paid keys cost $$. This approach:
- ✅ Proves the provider abstraction works
- ✅ Shows architectural flexibility without cost
- ✅ Keeps the demo fully free (only Gemini uses its free tier)
- ✅ Takes 10 minutes to swap mocks for real SDK calls when API keys are available

**Implementation details**: 
- `LoggedInferenceClient` (renamed from `LoggedGeminiClient`) accepts `provider` parameter
- Query param: `?provider=anthropic` or `?provider=openai` for testing
- All logging is identical regardless of provider (same inference_logs table)
- Mocked responses are intelligent (detect question type and respond appropriately)

---

## What I'd Improve with More Time

### Testing (Critical - 2-3 days)
- **Unit tests**: Django `TestCase` for models, serializers, views, SDK wrapper
  - Model tests: FK relationships, CASCADE/SET_NULL delete behavior, field validation
  - Serializer tests: Required fields, enum validation, null handling
  - View tests: CRUD endpoints, multi-turn context loading, error responses
  - SDK wrapper tests: Mock Gemini API, metadata capture, error re-raising, ingestion POST payload
- **Integration tests**: Full flow (message → LLM call → DB save → log ingestion)
- **Ingestion tests**: Invalid payloads, missing fields, type mismatches
- **Code coverage**: Target 80%+ for models/views/SDK; UI coverage lower priority

### Multi-Provider Support ⭐ IMPLEMENTED
- **google/gemini** (real, free tier) — Uses Google AI Studio free API key (no billing required)
- **anthropic/claude** (mocked) — Demonstrates architecture; real calls need paid API key
- **openai/gpt-4** (mocked) — Demonstrates architecture; real calls need paid API key

**Why mock Claude and GPT-4?** They don't have free tiers; paid API keys required ($). This approach shows the provider abstraction works while keeping the demo cost-free. To use real Claude/GPT-4: swap mock methods with actual SDK calls (10-min change).

**Usage:**
```bash
# Default: Gemini (free)
curl -X POST http://127.0.0.1:8000/api/conversations/{id}/messages/ -d '{"content":"hello"}'

# Try Claude (mocked)
curl -X POST "http://127.0.0.1:8000/api/conversations/{id}/messages/?provider=anthropic" -d '{"content":"hello"}'

# Try GPT-4 (mocked)
curl -X POST "http://127.0.0.1:8000/api/conversations/{id}/messages/?provider=openai" -d '{"content":"hello"}'
```

All providers log identically: provider name, model, latency, tokens, status, errors.

### Near-term (1-2 days)
- **Streaming responses**: SSE so tokens appear as they arrive (not as final block)
- **Token-based context truncation**: Use `tiktoken` to count tokens; truncate at 2000 tokens, not 20 messages
- **Postgres swap**: Support `DATABASE_URL` env var for easy local Postgres testing (bonus: Docker Compose makes this trivial)

### Medium-term (1 week)
- **Multi-provider abstraction**: Parameterize provider (Claude, GPT-4, etc.) with a pluggable interface
- **PII redaction**: Detect/mask emails, phone numbers before storage (privacy compliance)
- **Real-time dashboards**: WebSocket feed of logs → React dashboard (latency graphs, error rates)
- **Conversation search**: Full-text search on messages + logs
- **User authentication**: Per-user isolation, API keys for programmatic access

### Production (2+ weeks)
- **Kubernetes deployment**: Helm charts, auto-scaling, ingress
- **Event-driven ingestion**: Kafka/Redis Streams instead of HTTP POST
- **Audit logging**: Immutable log store (S3) for compliance
- **Cost tracking**: Per-conversation token spend, quotas, billing integration
- **Monitoring**: Prometheus metrics, Grafana dashboards, Alertmanager

---

## File Structure

```
OliveAssignment/
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── .env.example              # Template (checked in)
│   ├── .env                       # Actual secrets (git-ignored)
│   ├── db.sqlite3               # Local database (git-ignored)
│   ├── backend/                 # Django project package
│   │   ├── settings.py          # INSTALLED_APPS, DB config, CORS
│   │   ├── urls.py              # Mount /api/ routes
│   │   ├── asgi.py / wsgi.py
│   └── api/                     # Django app
│       ├── models.py            # Conversation, Message, InferenceLog
│       ├── views.py             # ConversationListCreateView, etc.
│       ├── serializers.py       # DRF serializers (validation)
│       ├── urls.py              # API route definitions
│       ├── admin.py             # Register models with customizations
│       ├── apps.py
│       ├── migrations/
│       └── sdk/
│           └── logged_client.py # LoggedGeminiClient wrapper
├── frontend/                    # Vite + React
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/
│   │   ├── App.jsx              # Main component (state, logic)
│   │   ├── App.css              # Sidebar, chat window styles
│   │   ├── api.js               # Fetch wrapper
│   │   ├── main.jsx
│   │   ├── index.css            # CSS variables, theme
│   │   └── components/
│   │       ├── Sidebar.jsx      # Conversation list
│   │       ├── ChatWindow.jsx   # Messages, input form
│   │       └── MessageBubble.jsx # Individual message UI
│   ├── public/                  # Static assets
│   └── node_modules/
├── .gitignore                   # venv, node_modules, .env, db.sqlite3
└── README.md                    # This file
```

---

## Testing

### Manual End-to-End
```bash
# Create conversation
curl -X POST http://127.0.0.1:8000/api/conversations/ \
  -H "Content-Type: application/json" \
  -d '{"title":"Test"}'

# Send message (captures schema, logs)
curl -X POST http://127.0.0.1:8000/api/conversations/{ID}/messages/ \
  -H "Content-Type: application/json" \
  -d '{"content":"What is 2+2?"}'

# Check logs (verify all fields)
curl http://127.0.0.1:8000/api/logs/ | python3 -m json.tool
```

### Browser Testing
1. Open `http://localhost:5173`
2. Create conversation, send messages
3. Verify multi-turn context
4. Check `/admin/` to inspect logs, schema

---

## Summary

This system demonstrates:
- **Sensible schema design**: Normalized tables, appropriate PK strategies, nullable vs cascading FKs
- **Practical tradeoffs**: SQLite for speed, replay pattern for stateless scalability, HTTP ingestion for resilience
- **Production readiness**: Error handling, CORS, DRF validation, audit-trail logs
- **Clean architecture**: Frontend, backend API, SDK wrapper, and ingestion are decoupled layers

All assignment requirements are met. The codebase is intentionally lean while being well-structured for extension.

---

## Getting Help

1. Verify `.env` has `GEMINI_API_KEY` (never paste in chat)
2. Both servers running (backend on 8000, frontend on 5173)
3. Database migrations applied (`python manage.py migrate`)
4. Check `/admin/` to inspect raw schema + data

Happy coding! 🚀
