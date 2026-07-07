# py-triage-engine

A Django REST API that receives payment webhook events and screens each
transaction through a deterministic rule engine, returning one of three
outcomes: AUTO_APPROVE, NEEDS_REVIEW, or AUTO_BLOCK. Flagged transactions
are enriched asynchronously with an LLM-generated explanation; when the
first-pass confidence is low or medium, an investigation agent gathers
additional context through tool calls before issuing a final verdict.

## Why This Project

Built to learn Django and DRF end-to-end by solving a concrete problem.
The goal was to get the rule engine and synchronous request cycle right
before adding any moving parts.

That worked until load testing revealed what happens when a slow
external call sits on the request thread. Under 500 concurrent users,
87.9% of requests failed. The fix was not to make the call faster; it
was to move it off the request thread entirely. That introduced async
enrichment — which introduced its own failure modes: blind retries
against a throttled dependency, and no way to see inside the pipeline
when something went wrong.

## Architecture

Request flow with layered separation:
- View — HTTP handler, validates request, returns 202 immediately
- Service — rule engine evaluation, idempotency check, enqueue logic
- Task — Celery async worker, circuit breaker check, LLM call with tool-calling investigation loop for low or medium confidence enrichments, enrichment persistence
- Beat — reconciliation job every 5 minutes; re-queues stale PENDING when circuit closed
- Repository — PostgreSQL via Django ORM, MongoDB via pymongo
- Observability — Prometheus metrics scrape; Grafana dashboard

## Tech Stack

Python 3.12 · Django 5 · Django REST Framework · Celery · Redis · PostgreSQL · MongoDB · Prometheus · Grafana · Docker · Docker Compose

## What's Implemented

- `POST /api/webhook/` — rule engine screens each transaction; returns 202 immediately
- Rule engine: AmountRule, FrequencyRule, GeoMismatchRule; deterministic score routing
- Idempotency guard with select_for_update; duplicate webhooks blocked at DB level
- Celery async worker decouples LLM enrichment from request thread; enrichment state machine: QUEUED; PROCESSING; COMPLETED; FAILED; PENDING
- Confidence-based escalation to tool-calling investigation agent; three read-only tools, hard cap 3 iterations, trace persisted to MongoDB
- Redis-backed circuit breaker with HALF-OPEN trial lock; graceful degradation to PENDING when circuit open; reconciliation job re-queues stale PENDING when circuit closed
- Polyglot persistence: PostgreSQL for transactions; MongoDB for enrichment documents; Prometheus metrics and Grafana dashboard instrument the full pipeline; agent iterations and tool calls exposed as Prometheus metrics

## Engineering Decisions

| Failure Mode | Without Fix | Solution |
|---|---|---|
| LLM call blocks request thread | 87.9% errors under 500 concurrent users | Celery async worker; API returns 202 immediately |
| Same webhook delivered twice | Duplicate MongoDB enrichment documents | select_for_update on enrichment_queued flag; second enqueue blocked at DB level |
| Celery retries exhausted silently | Transaction stays QUEUED forever | Catch retry exhaustion explicitly; write FAILED status to MongoDB |
| Enrichment schema varies per transaction type | Nullable columns or multiple tables in relational DB | MongoDB document store; flexible schema per enrichment document |
| LLM returns free-form text | Unparseable by downstream systems | System prompt constrains output to structured JSON with defined fields |
| LLM dependency throttled or down | Blind retry storm; worker queue backs up | Circuit breaker opens after N failures; fail-fast returns PENDING |
| Circuit OPEN leaves PENDING enrichments permanently | Dashboard shows stale state indefinitely | Reconciliation job re-queues PENDING when circuit CLOSED; eventual completeness |
| Multiple workers race on HALF-OPEN trial | Two workers both attempt trial LLM call | Redis SET NX EX trial lock; only one worker proceeds |
| Pipeline blind under async load | No visibility into bottleneck location | request_id flows end-to-end; Prometheus metrics per stage; Grafana dashboard |
| Low-confidence enrichment pushes investigation onto reviewers | Generic explanations; manual queries per case | Confidence-based escalation to tool-calling agent loop; LLM gathers context autonomously |
| Agent loop could run away on ambiguous cases | Unbounded LLM calls; cost and latency blowup | Hard cap at 3 iterations; forced finalize with accumulated context |
| Investigation queries scan unindexed columns | Sequential scans on user_id and merchant_name | Composite index (user_id, created_at); merchant_name index |

## Enrichment Output

LLM explanation is stored as structured JSON, not free-form text:

```json
{
  "summary": "Large transaction with a suspicious merchant in Bali.",
  "risk_factors": ["amount exceeds threshold", "suspicious merchant"],
  "recommended_action": "Block the transaction and investigate further.",
  "confidence": "high"
}
```

<details>
<summary>Dashboard response — enrichment COMPLETED</summary>

![dashboard_completed](./docs/benchmarks/async-enrichment/dashboard_completed.png)

</details>

<details>
<summary>Dashboard response — enrichment PENDING (circuit open)</summary>

![dashboard_pending](./docs/benchmarks/fault-tolerance/dashboard_pending.png)

</details>

## Agentic Investigation

One-shot enrichment has a blind spot: when the LLM lacks context, it
returns a low-confidence verdict with a generic explanation, pushing
the actual investigation onto the human reviewer — even though the
data needed (user history, prior flags, merchant patterns) already
sits in the system's own databases.

The fix is confidence-based escalation. First-pass enrichment stays
a single cheap call. If confidence comes back low or medium, the
transaction escalates to an investigation loop where the LLM can
request data through three read-only tools: user transaction history,
user flag history, and merchant flag statistics. The LLM decides
which tools to call and when it has enough context; Python executes
every query and feeds results back. Hard cap at 3 iterations, then
the agent is forced to finalize with available information.

The circuit breaker wraps the entire investigation as one unit — if
the circuit opens mid-loop, the investigation aborts to PENDING with
no partial state saved, and reconciliation restarts it from scratch.
Stateless restart over resumable state: partial findings can go stale
during a long circuit-open window, and a fresh start guarantees the
agent always decides from current data.

Investigation trace from a live run — borderline transaction
(risk_score 30, single rule), agent called all three tools before
finalizing at the iteration cap:

```json
"investigation_trace": {
  "iterations": 3,
  "tool_calls": [
    {"tool": "get_user_transaction_history", "args": {"user_id": "user-verify-agentic-3", "window_days": 30}},
    {"tool": "get_user_flag_history", "args": {"user_id": "user-verify-agentic-3"}},
    {"tool": "get_merchant_flag_stats", "args": {"merchant_name": "Toko Elektronik Jaya"}}
  ]
}
```

The final verdict referenced the merchant's 100% flag rate pulled
from tool data — a materially more specific explanation than the
first-pass alone could produce. Every trace is persisted to MongoDB
and surfaced in the dashboard so reviewers can see the agent's
reasoning path.

## Load Test — Synchronous Path (before fix)

Simulated a slow external call (2s latency) on the request thread to
measure behavior under concurrent load. 500 concurrent users, 50/s ramp.

| Metric | Result |
|---|---|
| Total requests | 2,742 |
| Failures | 2,409 (87.9%) |
| Avg latency | 20,334ms |
| Median latency | 27,000ms |
| 99th percentile | 37,000ms |
| RPS | 17.1 |

Key finding: a 2-second blocking call on the request thread causes
87.9% of requests to fail under 500 concurrent users. Thread pool
exhaustion means most requests never reach the rule engine.

<details>
<summary>Locust screenshot</summary>

![sync_loadtest](./docs/benchmarks/sync-baseline/sync_loadtest.png)

</details>

## Real-World Behavior — OpenRouter Rate Limiting

Under concurrent load, the free-tier LLM API returned 429 Too Many
Requests. The worker retried with 60s backoff but continued hitting
the rate limit. This is the behavior that motivated the circuit breaker:
instead of blind retrying against a throttled dependency, detect the
failure pattern and stop hammering it.

<details>
<summary>Worker log — 429 retry loop</summary>

![worker_429_retry](./docs/benchmarks/async-enrichment/worker_429_retry.png)

</details>

<details>
<summary>Worker log — successful enrichment</summary>

![worker_success](./docs/benchmarks/async-enrichment/worker_success.png)

</details>

## Circuit Breaker Behavior

When the circuit opens, the worker skips the LLM call entirely.
Task completes in ~0.03s instead of 2-4s. Enrichment status is
set to PENDING. The rule engine verdict is unaffected.
When the circuit closes, the reconciliation job re-queues
stale PENDING enrichments automatically.

<details>
<summary>Worker log — circuit open, LLM call skipped</summary>

![circuit_open_skip](./docs/benchmarks/fault-tolerance/circuit_open_skip.png)

</details>

<details>
<summary>Worker log — reconciliation skipped (circuit open)</summary>

![reconciliation_skipped](./docs/benchmarks/fault-tolerance/reconciliation_skipped.png)

</details>

<details>
<summary>Worker log — reconciliation re-queued pending enrichments</summary>

![reconciliation_requeue](./docs/benchmarks/fault-tolerance/reconciliation_requeue.png)

</details>

## Observability

Structured logging with request_id flowing end-to-end from webhook
ingestion through Celery worker to LLM call. Every log line is JSON
with consistent fields: timestamp, level, request_id, event, status,
duration_ms. Six Prometheus metrics expose pipeline health in real time;
Grafana dashboard visualizes all six panels with 10s refresh.

Under 500 concurrent users, Grafana captured LLM call duration spiking
from 5s baseline to p95 of 25s, reconciliation job re-queuing 47 stale
PENDING enrichments, and queue depth draining to 0 as the system
recovered without intervention.

<details>
<summary>Structured log — request_id end-to-end</summary>

![structured_log](./docs/benchmarks/observability/structured_log.png)

</details>

<details>
<summary>Prometheus metrics — /metrics endpoint</summary>

![prometheus_metrics](./docs/benchmarks/observability/prometheus_metrics.png)

</details>

<details>
<summary>Grafana dashboard — under load</summary>

![grafana_dashboard_load](./docs/benchmarks/observability/grafana_dashboard_load.jpeg)

</details>

<details>
<summary>Grafana dashboard — after reconciliation</summary>

![grafana_dashboard_recovered](./docs/benchmarks/observability/grafana_dashboard_recovered.png)

</details>

## Run Locally

```bash
docker compose up --build

cp .env.example .env
# fill in OPENROUTER_API_KEY and OPENROUTER_MODEL in .env

python -m pytest apps/ -v
```