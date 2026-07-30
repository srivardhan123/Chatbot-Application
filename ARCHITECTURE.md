# Architecture Notes: LLM Inference Logging System

**Purpose**: Deep-dive into system design, ingestion flow, logging strategy, scaling considerations, and failure handling assumptions.

---

## Ingestion Flow

### End-to-End Request: Sending a Message

```
1. User sends message "What is 2+2?" in React UI
        │
        ▼
2. POST http://127.0.0.1:8000/api/conversations/{id}/messages/
   Body: {"content": "What is 2+2?"}
        │
        ▼
3. Django View (ConversationMessagesView.post):
   a) Save user message to DB
      → INSERT INTO api_message (conversation_id, role, content, created_at)
         VALUES ({id}, 'user', 'What is 2+2?', NOW())
   
   b) Query last 20 messages from this conversation
      → SELECT * FROM api_message 
        WHERE conversation_id={id} 
        ORDER BY created_at DESC 
        LIMIT 20
      (Indexed on: conversation_id, -created_at)
   
   c) Reverse order for chronological replay
      → history = [{role: 'user', content: '...'}, ...]
   
   d) Instantiate LoggedGeminiClient(api_key, model="gemini-flash-latest")
   
   e) Call client.send(
        session_id={conversation_id},
        conversation_id={conversation_id},
        messages=history
      )
        │
        ├─────────────────────────────────────┐
        │                                      │
        ▼                                      ▼
4a. LoggedGeminiClient.send():           4b. (After step 4a completes)
    ┌──────────────────────────┐             HTTP POST /api/logs/
    │ 1. Record start_time     │             with payload:
    │    (time.monotonic())    │             {
    │                          │               "conversation": "{id}",
    │ 2. Build Gemini request  │               "session_id": "{id}",
    │    from history          │               "provider": "google",
    │                          │               "model": "gemini-flash-latest",
    │ 3. Call Gemini API       │               "latency_ms": 2024.5,
    │    google.genai.Client   │               "input_tokens": 651,
    │    .models               │               "output_tokens": 28,
    │    .generate_content()   │               "status": "success",
    │                          │               "error_message": null,
    │ 4. Record end_time       │               "input_preview": "What is 2+2?",
    │    latency_ms =          │               "output_preview": "2 + 2 = 4"
    │    (end - start) * 1000  │             }
    │                          │             │
    │ 5. Extract metadata:     │             ▼
    │    - response.text       │        5b. LogIngestListView.post():
    │    - response.usage_metadata         (DRF endpoint)
    │      ├─ input_tokens     │             │
    │      └─ output_tokens    │             ├─ Validate with
    │    - truncate previews   │             │  InferenceLogSerializer
    │      (first 200 chars)   │             │
    │                          │             ├─ Extract fields
    │ 6. Build payload dict    │             │
    │    (12 fields)           │             └─ INSERT into api_inferencelog
    │                          │                → InferenceLog.objects.create(
    │ 7. POST to /api/logs/    │                   conversation_id, session_id,
    │    requests.post(        │                   provider, model, latency_ms,
    │      url,                │                   input_tokens, output_tokens,
    │      json=payload,       │                   status, error_message,
    │      timeout=5s          │                   input_preview, output_preview,
    │    )                     │                   created_at=NOW()
    │                          │                 )
    │ 8. Return reply text     │
    │    OR re-raise exception │
    └──────────────────────────┘
        │
        ▼
4c. Back in Django View:
    If success (no exception):
    ├─ Extract assistant_message.text from client.send()
    ├─ Save Message(role="assistant", content=reply)
    │  → INSERT INTO api_message (conversation_id, role, content, created_at)
    │     VALUES ({id}, 'assistant', '{reply}', NOW())
    │
    └─ Return HTTP 201 CREATED:
       {
         "user_message": {...},
         "assistant_message": {...}
       }
    
    If error (exception raised):
    ├─ Catch exception
    ├─ (Logging already happened in SDK wrapper)
    │
    └─ Return HTTP 502 BAD_GATEWAY:
       {
         "user_message": {...},
         "error": "{exception message}"
       }
        │
        ▼
5. Frontend receives response:
   ├─ Append user_message bubble
   ├─ Append assistant_message bubble (or error)
   ├─ Scroll to bottom
   └─ Update UI state
```

### Key Design Points

1. **User message saved BEFORE LLM call**: If Gemini times out, user's message is never lost
2. **Logging is async (HTTP POST)**: Doesn't block view response; failures are silent
3. **Metadata captured for all outcomes**: Success, error, timeout—all logged with latency
4. **Last 20 messages = context window**: Trades token cost vs context completeness
5. **Ingestion endpoint is real HTTP**: Demonstrates SDK → ingestion boundary; future-proof for queuing

---

## Logging Strategy

### What Gets Captured

```
Per API call, InferenceLog captures:

1. Request Context
   ├─ conversation_id (FK, nullable, SET_NULL)
   ├─ session_id (session UUID as string)
   └─ created_at (auto timestamp)

2. Model Info
   ├─ provider ("google")
   ├─ model ("gemini-flash-latest")
   └─ (extensible for multi-provider)

3. Performance
   ├─ latency_ms (float, always populated)
   ├─ input_tokens (int, null if error/no usage data)
   └─ output_tokens (int, null if error/no usage data)

4. Status
   ├─ status ("success" or "error")
   └─ error_message (null if success, exception string if error)

5. Content Previews
   ├─ input_preview (first 200 chars of user prompt)
   └─ output_preview (first 200 chars of LLM reply)
```

### Why This Schema

| Field | Rationale |
|-------|-----------|
| `latency_ms` always captured | Distinguishes failure modes: auth errors (fast), timeouts (slow), connection hangs (very slow) |
| `input/output_tokens` nullable | Some providers don't return token counts; using null avoids magic numbers (-1, 0) |
| `input/output_preview` truncated | Full messages in `Message` table; logs are for ops/monitoring (quick glance). 200 chars = typical summary, saves storage. |
| `conversation_id` nullable + SET_NULL | Logs are audit-trail artifacts; if conversation deleted, logs survive for post-mortem analysis |
| `session_id` as string (not FK) | Allows logging to happen before transaction commits; if conversation save fails after LLM call, log still exists |

### Logging Failure Modes

```
Scenario 1: Gemini API Error
┌──────────────────────────┐
│ LoggedGeminiClient.send()│
│ ├─ Call Gemini          │
│ ├─ Exception raised      │ ← e.g., 401 Unauthorized
│ ├─ Build error payload   │
│ └─ POST to /api/logs/    │
│    status="error"        │
│    error_message="401..."│
└──────────────────────────┘
          │
          ├─ Log POST succeeds
          │  → Logged with status="error"
          │
          └─ Log POST fails (timeout, connection refused)
             → Exception swallowed
             → User gets error bubble anyway
             → Log is lost (traded for chat reliability)

Scenario 2: Ingestion Endpoint Down
┌──────────────────────────┐
│ LoggedGeminiClient.send()│
│ ├─ Call Gemini: SUCCESS │
│ ├─ Build payload         │
│ └─ POST to /api/logs/    │
│    timeout: 5s           │
│    requests.RequestException
│    (ConnectionRefusedError)
│    │
│    └─ except: pass       │ ← Silently swallowed
└──────────────────────────┘
          │
          └─ Return reply to user
             (log is lost, but chat succeeds)
             Production: emit metric/alert separately
```

### Query Patterns

```python
# Dashboard: All API calls in last hour
InferenceLog.objects.filter(
    created_at__gte=now() - timedelta(hours=1)
)

# Error analysis: All failed calls
InferenceLog.objects.filter(status="error").values(
    "error_message", "model"
).annotate(count=Count("id"))

# Performance: P95 latency by model
InferenceLog.objects.values("model").annotate(
    p95_latency=Percentile("latency_ms", 0.95)
)

# Token spend: Total tokens used per conversation
InferenceLog.objects.values("conversation").annotate(
    total_input=Sum("input_tokens"),
    total_output=Sum("output_tokens")
)
```

---

## Scaling Considerations

### At 10 requests/second (Small MVP)
- **DB**: SQLite (local file), single process
- **Writes**: ≈ 30 rows/sec (2 Message + 1 InferenceLog per request)
- **Storage**: ≈ 180 rows/min × 1KB = 180KB/min = 259MB/day ≈ 95GB/year
- **Query latency**: `SELECT * FROM Message WHERE conversation_id=? LIMIT 20` with index = ≈ 50-100ms
- **Bottleneck**: Nothing; single machine handles easily
- **Setup**: Default SQLite works fine

### At 100 requests/second (Growing)
- **DB**: Postgres (RDS or self-hosted)
- **Writes**: ≈ 3000 rows/sec
- **Connection pool**: pgbouncer (max_client_conn=1000)
- **Storage**: ≈ 2.6TB/year (at 1KB/row avg)
- **Query latency**: With indexes, still ≈ 100ms for conversation context
- **Bottleneck**: Single Postgres instance (memory, CPU); need read replicas
- **Changes needed**:
  - Swap SQLite → Postgres (change `DATABASES` in settings)
  - Add read replicas for analytics queries
  - Increase `HISTORY_LIMIT` token budget or implement token-based truncation

### At 1000+ requests/second (Production Scale)
- **DB**: Postgres with read replicas (3+)
- **Analytics DB**: Separate ClickHouse or BigQuery cluster (materialized views of InferenceLog)
- **Caching**: Redis for conversation list (frequently accessed, rarely changes)
- **Message queue**: Celery + RabbitMQ for async logging (don't POST sync)
- **Sharding**: Shard InferenceLog by `conversation_id` (month-based partition) to distribute data
- **Query patterns**:
  - Chat (tail latency): Postgres primary (SLA: < 200ms p99)
  - Analytics (batch): ClickHouse (SLA: < 10s for hourly rollups)
- **Changes needed**:
  - Event-driven architecture (produce: message created → consume: log to ClickHouse)
  - Separate service for ingestion (Kafka topic: `inference-logs`)
  - Separate service for analytics (daily batch jobs)

### Storage Estimates

```
Per message: ≈ 0.5KB (id, conversation_id, role, content, timestamp)
Per log: ≈ 0.5KB (all fields + JSON serialization overhead)

At 100 req/s:
- 30 rows/sec (messages) × 86,400 sec/day = 2,592,000 messages/day ≈ 1.3TB/day
- 100 req/s × 86,400 sec/day = 8,640,000 logs/day ≈ 4.3TB/day
- Total: ≈ 5.6TB/day ≈ 2PB/year

Retention policy (production):
- Hot data (< 30 days): Postgres primary + replicas
- Warm data (30-90 days): Archive to S3 / cold storage
- Logs only (> 90 days): S3 / Glacier for compliance
```

---

## Failure Handling Assumptions

### Assumption 1: Gemini API is Eventually Available
**Scenario**: Gemini times out or returns 503 Service Unavailable  
**Assumption**: Temporary; retry with exponential backoff  
**Implementation**: SDK retries built-in; if persists, logged as error  
**User sees**: "Something went wrong; check your connection"

### Assumption 2: Database Is Available at Request Time
**Scenario**: SQLite is locked (concurrent writes in production)  
**Assumption**: Won't happen in dev (single process); production would use Postgres  
**Implementation**: Django ORM handles connection pooling (Postgres)  
**Failure**: Request returns 500; user sees error; log is lost (no transaction)

### Assumption 3: Logging Failures Don't Cascade
**Scenario**: Ingestion endpoint down, HTTP POST timeout  
**Assumption**: Acceptable for this MVP; production would retry async  
**Implementation**: Exceptions swallowed; no retry  
**Failure**: Log is lost, but user's chat succeeds  
**Monitoring**: Production would emit metrics (Prometheus) so ops knows logging is down

### Assumption 4: Message History Is Immutable
**Scenario**: User sends message; later tries to edit it  
**Assumption**: Not supported; messages can only be deleted (with conversation)  
**Implementation**: No UPDATE endpoints for messages  
**Failure**: User can't edit; must start new conversation  
**Future**: Add conversation branching (fork at message N) for alternative paths

### Assumption 5: No Concurrent Edits to Same Conversation
**Scenario**: Two browser tabs open same conversation, both send messages simultaneously  
**Assumption**: Race condition; last write wins; both messages saved  
**Implementation**: No optimistic locking or row-level locks; SQLite is sequential anyway  
**Failure**: Messages interleaved in DB; context is slightly wrong but still coherent  
**Production**: Add `version` field to Conversation; reject on conflict

### Assumption 6: Network Connection Lasts for Full Chat Session
**Scenario**: User sends message, frontend crashes before response fully received  
**Assumption**: Message is saved; frontend can re-fetch history on reload  
**Implementation**: User message committed before LLM call; fetch history on page load  
**Failure**: Message appears in history on next load; user sees it's already there  
**No data loss**: Idempotent refresh is safe

---

## Error Recovery Flows

### Flow 1: User Sends Message → Gemini Timeout

```
Frontend sends POST /api/conversations/{id}/messages/
│
↓
Django saves Message(role="user", content="hello")  ← Committed immediately
│
↓
Call LoggedGeminiClient.send()
├─ Gemini API takes 35s (exceeds 30s timeout)
├─ Exception: TimeoutError
│
├─ LoggedGeminiClient:
│  ├─ Record latency_ms ≈ 30000
│  ├─ POST to /api/logs/ with status="error"
│  ├─ Re-raise TimeoutError
│
↓
Django View catches exception
├─ Return HTTP 502 with {user_message, error: "Timeout..."}
│
↓
Frontend shows:
├─ User message bubble (already saved)
├─ Error bubble (red) with "Something went wrong"
├─ User can retry (sends new message) or refresh
│
Result: Message NOT lost; error is visible; user can retry
```

### Flow 2: Ingestion Endpoint Down

```
LoggedGeminiClient successfully calls Gemini
├─ Receive reply text ✓
├─ Extract latency, tokens ✓
├─ Build payload ✓
│
├─ HTTP POST to http://127.0.0.1:8000/api/logs/
│  ├─ Connection refused (server down)
│  ├─ requests.ConnectionError raised
│
├─ except requests.RequestException:
│  └─ pass (silently swallow)
│
├─ Return reply text to view ✓
│
↓
Django View returns HTTP 201 with {user_message, assistant_message}
│
↓
Frontend shows:
├─ User message bubble ✓
├─ Assistant message bubble ✓
├─ (No error, user doesn't know log failed)
│
Result: Chat succeeds; log is lost (acceptable tradeoff for MVP)
Production: Emit Prometheus metric so ops alerts on failed logs
```

### Flow 3: Database Connection Lost

```
Django trying to save Message(...)
├─ Database connection fails
├─ django.db.DatabaseError raised
│
├─ Exception bubbles up (no retry logic)
│
↓
Django View returns HTTP 500
│
↓
Frontend shows error bubble
│
Result: Message is lost (no recovery in MVP)
Production: Implement connection pooling + retry logic
```

---

## Future: Event-Driven Ingestion

**Current**: HTTP POST (blocking, failing silently)

```
LoggedGeminiClient
├─ Call Gemini
├─ HTTP POST to /api/logs/ (5s timeout, exception swallowed)
└─ Return to view
```

**Future**: Queue-based (non-blocking, guaranteed delivery)

```
LoggedGeminiClient
├─ Call Gemini
├─ Produce: KafkaProducer.send("inference-logs", payload) (non-blocking)
└─ Return to view immediately

Separate service: Ingestion Consumer
├─ Consume from Kafka
├─ Validate payload
├─ Write to database
├─ Dead-letter queue for failures (manual retry)
```

**Benefits**:
- Logging never blocks chat response
- Guaranteed delivery (Kafka retries internally)
- Scale independently (add consumers if ingestion lags)
- Dead-letter queue for error recovery

---

## Summary

This architecture prioritizes:
1. **User experience**: Logging failures never break chat
2. **Simplicity**: HTTP POST is easier than Kafka for MVP
3. **Debuggability**: All metadata captured, queryable via Django admin
4. **Extensibility**: HTTP boundary makes it easy to swap in Kafka/Redis later
5. **Scalability**: SQL schema is normalized; can shard/replicate when needed

For MVP: This is production-grade. For scale (100+ req/s): Swap SQLite → Postgres, add Redis caching, event-driven ingestion.
