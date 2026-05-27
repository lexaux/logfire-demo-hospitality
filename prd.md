
Integration Support Assistant
Logfire Observability Demo App — Original Build Spec

> Note: this PRD captures the original spec and may be partially out of sync with the
> current code. The integrations have been generalized from PMS-specific to common
> developer integrations (Stripe / Twilio / SendGrid); the rest of the build still
> reflects the same shape and Logfire features.

1. Overview
A realistic internal support tool. A user submits a ticket describing an issue with a third-party
integration (e.g. Stripe, Twilio, SendGrid). An AI agent investigates using four tools, returns a
structured resolution, and every step is fully traced in Logfire.

The demo punchline: open Logfire alongside the running app and show a single ticket as a trace tree — HTTP request → DB write → AI agent → 2–3 dynamic tool calls → structured result.

2. Tech Stack
Layer	Technology
Backend	FastAPI + SQLAlchemy (SQLite) - run dependencies in docker
AI	OpenAI GPT-4o with function calling
Doc search	Keyword/chunk search over markdown files (no vector DB)
Frontend	Single HTML file, vanilla JS — no framework
Observability	Logfire (auto + manual instrumentation)
Evals	Pydantic Evals — offline + online
3. Knowledge Base Documents
Four pre-written markdown files in /data/docs/. Intentionally imperfect — some things are ambiguous so the AI occasionally returns low confidence. Each doc uses consistent section headers: ✅ Supported / ⚠️ Partial/quirks / ❌ Not supported / 🐛 Known bugs

File	System	Key content
stripe.yaml	Stripe Payments	Payment Intents, webhooks, refunds, known bugs (BUG-S###)
twilio.yaml	Twilio Programmable Messaging	SMS / voice / Verify, A2P 10DLC, known bugs (BUG-T###)
sendgrid.yaml	SendGrid Email	Transactional send, event webhook, suppressions, known bugs (BUG-G###)

Common topics: 
Listing sync
one-way or two-way
fields: 
name
nickname
address (full)
custom fields
wifi setting
photos

reservation/guest sync
Some fields are one-way others are two way sync
sync nature: webhooks (immediate update) or regular poll (5 minute delay)
fields: 
- listing
- dates times of check in-out
- guest
  - name
  - email
  - phone
  - notes
- payment status
- confirmation code from OTA (Airbnb)

Messaging: 
- per channel - what is supported and not. features: sending messages, receiving messages, 2-way sync (posting our messages to PMS)
- extra features - attachments

4. App Data Model (SQLite)
tickets
id, created_at, subject, description, submitted_by
integration         (stripe | twilio | sendgrid)
status              (open | resolved | escalated)
ai_category
ai_priority
ai_confidence
ai_resolution_suggestion
source_docs_referenced   -- JSON array of doc names
similar_ticket_ids       -- JSON array
trace_id                 -- Logfire trace deep-link key
seeded_tickets (pre-populated resolved tickets for similarity search)
Same schema as tickets, plus:

resolution_notes    -- text
Pre-seed 25–30 realistic resolved tickets at startup covering common PMS/guest platform issues.

5. AI Agent & Tools
Agent behaviour
The agent is dynamic — it decides which tools to call based on ticket content. Simple tickets may call only one tool. Ambiguous or P1 tickets call all three. This variability is what makes the Logfire trace tree interesting.

Tool 1 — search_integration_docs(query, systems[])
Input	Natural language query + list of relevant systems from ticket
Implementation	Chunk the markdown docs at startup. Keyword match query against chunks. Return top 3 chunks with doc name + section.
Returns	[{ doc, section, content, relevance_score }]
Logfire span attrs	query, systems_searched, chunks_returned, latency_ms
Tool 2 — find_similar_tickets(description, system_filter?)
Input	Ticket description text, optional system filter
Implementation	Keyword overlap against seeded_tickets table in SQLite. Return top 2 matches with score.
Returns	[{ ticket_id, subject, resolution_notes, similarity_score }]
Logfire span attrs	query_terms, tickets_scanned, matches_returned, top_score
Tool 3 — get_escalation_context(priority, pms_system)
When called	Only when agent assigns P1 priority OR confidence is low — not always called
Implementation	Simple lookup from a hardcoded dict/JSON file per system: SLA, owner team, degraded status
Returns	{ sla_hours, owner_team, currently_degraded, escalation_notes }
Logfire span attrs	priority_in, system, degraded_flag, owner_team
Structured output from agent
category               (billing | sync_issue | config | not_supported | bug | unknown)
priority               (P1 | P2 | P3)
confidence             (high | medium | low)
resolution_suggestion  (text, 2–4 sentences)
source_docs_referenced (list of doc names used)
similar_ticket_ids     (list of IDs referenced)
escalation_recommended (bool)
6. Logfire Trace Structure
Every ticket submission produces one root trace with this shape:

POST /tickets                              ← root HTTP span (auto-instrumented)
├── ingest_ticket                          ← SQLAlchemy INSERT (auto)
├── ai_agent_run                           ← manual logfire.span()
│   ├── openai.chat                        ← auto (shows model, prompt tokens, completion tokens)
│   ├── tool:search_integration_docs       ← manual span with attrs
│   ├── tool:find_similar_tickets          ← manual span → SQLAlchemy SELECT
│   ├── tool:get_escalation_context        ← manual span (P1 / low-conf only)
│   └── openai.chat                        ← synthesis call, structured output
└── update_ticket                          ← SQLAlchemy UPDATE (auto)
The third tool appears only on complex tickets. The variable-depth tree is the key visual in Logfire.

7. Frontend
Single index.html. Two tabs, no framework, no build step.

Submit tab
PMS dropdown (Mews / Opera / Cloudbeds)
Guest platform dropdown (Canary / Duve / Roomkey)
Textarea: describe the issue
Submit → loading state → AI result card
Result card: category badge, priority badge, confidence badge, resolution text, docs referenced, similar ticket IDs
🔍 View in Logfire link on every result card (uses trace_id)
Recent tickets tab (lightweight, no filters)
Table: subject, systems, category, priority, confidence, View trace link
Last 10 tickets only
8. Pydantic Evals
Offline evals
Run from CLI against the agent directly — no HTTP, no DB. Input is a ticket dict, output is scored against expected values.

Dataset — 8 test cases
#	Ticket	Expected category	Expected priority	Expected confidence
1	Mews check-in not triggering Canary message	sync_issue	P2	high
2	Opera on-prem rate sync broken	not_supported	P1	high
3	Early check-in upsell silent failure	config	P2	low
4	Webhook firing twice on reservation	bug	P1	high
5	Cloudbeds OTA passthrough missing fields	sync_issue	P2	medium
6	Duve guest messaging delay >10 min	unknown	P2	low
7	Opera cloud vs on-prem feature gap	not_supported	P3	high
8	Roomkey minibar sync not in docs	unknown	P3	low
Scoring functions (3)
Scorer	Logic
category_match	Exact match — 1.0 or 0.0
priority_match	Exact match, but P1 false negatives always score 0.0 (never miss a P1)
escalation_llm_judge	LLM-as-judge: given ticket + confidence=low, was escalation recommended correctly? Returns 0.0–1.0 with reasoning
The LLM judge scorer is itself a demo moment — an AI evaluating an AI, both visible as Logfire traces.

Online evals
Same scoring functions wired into the live request path. After each ticket is processed, scores are attached to the root trace as Logfire span attributes.

Implementation	Call scorers after agent returns, attach via logfire.set_attribute() on root span
What Logfire shows	Filter traces by eval_priority_match < 1.0 to find all P1 misses in real time
9. Demo Scenarios
Four pre-scripted tickets. Run them in order — they tell a progressive story.

#	Ticket	What it demonstrates
1 — Happy path	Guest messages not triggering in Canary after Mews check-in	Both tools return results, high confidence, clean 2-tool trace, evals score 1.0
2 — Clear not-supported	Opera on-prem rate sync broken with Cloudbeds	Docs say "not supported on-prem", AI cites source doc, confidence=high, evals score 1.0
3 — Ambiguous / escalate	Early check-in upsell not working, no error shown	Docs unclear, similar ticket unresolved, all 3 tools called, confidence=low, escalation recommended, LLM judge fires
4 — Known bug match	Webhook firing twice on every reservation	find_similar_tickets returns resolved ticket with fix, AI references it directly, shortest trace
10. Build Order & Time Budget
Block	Time	What to build
1 — Foundation	0:00 – 0:30	Project scaffold, Logfire init, FastAPI app, SQLAlchemy models, seed script (docs + 25 resolved tickets)
2 — Tools	0:30 – 1:15	Tool 1 (doc chunk search), Tool 2 (SQLite similarity), Tool 3 (escalation lookup). Each wrapped in logfire.span() with attributes.
3 — AI Agent	1:15 – 2:00	OpenAI function calling, dynamic tool selection, structured output parsing, logfire annotations on agent run
4 — Frontend	2:00 – 2:30	Single HTML file, submit form, result card, recent tickets table, Logfire trace deep-links
5 — Offline Evals	2:30 – 3:10	Pydantic eval dataset (8 cases), 3 scoring functions including LLM judge, CLI eval runner
6 — Online Evals	3:10 – 3:40	Wire scoring into live request path, attach scores to root span via logfire.set_attribute()
7 — Polish & run	3:40 – 4:00	Run all 4 scenarios, run offline eval suite, verify traces, write README
11. Project File Structure
support-assistant/
├── main.py                   # FastAPI app, routes, Logfire setup
├── agent.py                  # AI agent, OpenAI function calling, tool dispatch
├── tools/
│   ├── doc_search.py         # Tool 1: chunk search over markdown docs
│   ├── ticket_search.py      # Tool 2: SQLite similarity search
│   └── escalation.py         # Tool 3: escalation context lookup
├── models.py                 # SQLAlchemy models
├── seed.py                   # Seed script: docs + resolved tickets
├── evals/
│   ├── dataset.py            # 8 eval test cases
│   ├── scorers.py            # category_match, priority_match, llm_judge
│   └── run_evals.py          # CLI offline eval runner
├── data/
│   ├── docs/                 # 4 markdown integration docs
│   └── seeded_tickets.json   # 25 pre-resolved tickets
├── frontend/
│   └── index.html            # Single-file UI
└── README.md
12. Logfire Features Demonstrated
Feature	Where it appears
Auto HTTP spans	Every FastAPI request, zero config
Auto SQLAlchemy spans	DB inserts, selects, updates as child spans
Auto OpenAI spans	Both LLM calls show model, prompt tokens, completion tokens
Manual logfire.span()	ai_agent_run + each of the 3 tool spans
Span attributes	Tool inputs/outputs, similarity scores, chunk counts, confidence
Variable trace depth	2-tool vs 3-tool traces visible side-by-side in Logfire UI
Trace deep-links	Every result card and ticket row links directly into Logfire
Online eval scores	eval_category_match, eval_priority_match on each root trace
Error / low-conf spans	Scenario 3 surfaces as a flagged trace in Logfire
