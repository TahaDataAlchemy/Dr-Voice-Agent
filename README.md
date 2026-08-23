# Patient Voice Agent

A voice AI agent on a real U.S. phone number that registers new patients through natural conversation,
persists them to Postgres, and exposes them through a REST API and a small dashboard.

| | |
|---|---|
| **Phone number** | `+1 (___) ___-____` ← filled in after deployment (see *Live demo*) |
| **API base URL** | `https://patient-voice-agent.onrender.com` ← filled in after deployment |
| **Dashboard** | `https://<api-base>/app` · demo login `demo@example.com` / `demo12345` |
| **API docs** | `https://<api-base>/docs` (OpenAPI) |

> Built for a take-home assessment. No real patient data is stored; seed data is fictional.

---

## Architecture

```
 Caller ──PSTN──▶  Vapi  (phone number · Deepgram STT · TTS voice · turn-taking & barge-in · recording)
                    │      runs the per-turn LLM loop with OUR prompt + tool schemas
                    │      (provider: OpenRouter, model: openai/gpt-oss-120b, your key)
                    │
                    │  tool-calls ─────▶ POST /api/v1/voice/webhook   capture_fields · lookup_patient_by_phone ·
                    │  status · transcript · end-of-call-report        register_patient · update_patient · schedule
                    ▼
      ┌────────────────────────── FastAPI backend (Render, Docker) ──────────────────────────┐
      │  modules/voice     webhook dispatcher · tools · assistant config as code                │
      │                    (+ LangChain custom-LLM loop, VOICE_LLM_MODE=custom)                 │
      │  modules/patients  validators · PatientService · REST /patients (spec)                  │
      │  modules/calls     live call state, transcripts, captures, outcomes                     │
      │  modules/analysis  LangChain → OpenRouter: post-call analysis + "ask about this call"   │
      │  modules/auth      JWT login for the dashboard                                          │
      │  modules/dashboard stats + status                                                       │
      │  static/           Next.js dashboard (static export) served at /app                     │
      └──────────────────────────────────┬───────────────────────────────────────────────────┘
                                         ▼
                         Supabase Postgres  (users · patients · calls, Alembic migrations)
```

**Division of labour.** Vapi owns the timing-critical audio loop: number, transcription, voice, barge-in,
recording, and — in the default mode — the per-turn LLM call, made with *our* system prompt, *our* tool
definitions and the OpenRouter model we choose. Our backend sits on the **tool path**: every
`capture_fields` / `register_patient` / … call hits `/api/v1/voice/webhook`, where validation and
persistence run through exactly the same service layer as the REST API. Call-lifecycle events (status,
transcript, end-of-call report with recording) arrive on the same webhook and drive the dashboard; the
post-call analysis and the transcript Q&A run through LangChain after the fact, where latency is free.
`VOICE_LLM_MODE=custom` flips the assistant to Vapi's custom-LLM mode and runs the conversation loop in our
LangChain agent instead (see *Known limitations* for why that is not the default).

Full request flows, endpoint and screen reference: **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.

### Call flow

1. Vapi answers and speaks the greeting (no backend call needed — survives a cold start).
2. The agent collects **name → phone → date of birth → sex → address → email (optional)**. After every
   answer it calls `capture_fields`, which validates + normalizes and stores a draft on the call row.
   Invalid values come back as field-specific `errors`, so the agent re-prompts for *that field only*.
3. When the phone number is captured the server checks for an existing active patient with that number →
   *"It looks like we already have a record for Jane Doe. Would you like to update your information
   instead?"* (→ `update_patient`).
4. The agent offers the optional extras with the spec's wording (insurance, emergency contact, language).
5. Read-back confirmation → `register_patient` (full payload, validated again server-side, written through
   `PatientService`). Failures are relayed: retry once, then apologise and end gracefully.
6. *"You're all set, Jane. … Take care, goodbye."* → built-in `endCall` tool (plus `endCallPhrases` and a
   call-control fallback). The end-of-call report finalizes the call and triggers the post-call analysis.

---

## Tech stack & why

| Layer | Choice | Why |
|---|---|---|
| Telephony / STT / TTS | **Vapi** | Free U.S. number, Deepgram + TTS + turn-taking out of the box; custom-LLM mode lets us keep the brain in our code. |
| Conversation LLM | **OpenRouter `openai/gpt-oss-120b`** (run by Vapi with our prompt/tools) | Your key, your model choice, swappable by env var; Vapi keeps the streaming/TTS pipelining and barge-in. |
| Analysis / Q&A | **LangChain** (`langchain-openai` → OpenRouter) | Structured-output post-call analysis and the transcript chat; also the optional custom-LLM loop + terminal chat. |
| Backend | **FastAPI** (modular `core` + `modules` layout) | Async SSE streaming for the custom-LLM endpoint, pydantic validation, OpenAPI docs for free. |
| Data | **SQLModel + Alembic on Supabase Postgres** | Typed models, real constraints (NOT NULL, CHECK, regex on phone/zip), migrations; SQLite for tests. |
| Dashboard | **Next.js 16 (static export) + Tailwind + TanStack Query** | Served by FastAPI at `/app` → one deployable; polling keeps the live-call banner fresh. |
| Hosting | **Render** (Docker) | One free web service; Supabase hosts the database. |

---

## Running locally

Prerequisites: Python 3.11 (`uv` installs it), Node 22, `uv`.

```bash
cp .env.example .env                     # fill in keys (see Environment variables)
uv sync                                  # Python deps (creates .venv)
uv run python scripts/build_frontend.py  # builds Next.js into ./static (optional for API-only work)
uv run python main.py -d                 # http://localhost:8000  (API docs at /docs, dashboard at /app)
uv run pytest                            # 38 tests: validators, REST API, auth, tools, agent loop, webhook
```

With no `DATABASE_URL` the app uses SQLite (`./data/dev.db`) and seeds two fictional patients plus the demo
login. Point `DATABASE_URL` at Supabase (session pooler URI) to run against Postgres — migrations apply on
startup.

### Talking to the agent without a phone

```bash
uv run python scripts/chat.py --caller +14155550139   # terminal chat through the same LangChain loop
```

### Connecting Vapi (needs a public HTTPS URL)

```bash
cloudflared tunnel --url http://localhost:8000        # or ngrok http 8000
uv run python scripts/setup_vapi.py --base-url https://<tunnel-host>
```

`setup_vapi.py` creates/updates the assistant from `modules/voice/assistant_config.py` (system prompt, tool
schemas → webhook URL + secret, OpenRouter model, voice, transcriber, `endCall` tool, recording), registers
your OpenRouter key as a Vapi provider credential, and attaches a free Vapi number (creating one if needed). It is idempotent — rerun it after changing the base URL. On Render the app does the
same on boot (`VAPI_SYNC_ON_STARTUP=true`, using `RENDER_EXTERNAL_URL`).

---

## Deployment (Render + Supabase)

1. **Supabase** → new project → *Project Settings → Database → Connection string → Session pooler* →
   `DATABASE_URL`. (The direct `db.<ref>.supabase.co` host is IPv6-only; Render needs the pooler.)
2. **Render** → *New → Blueprint* → this repo → `render.yaml` creates the web service and prompts for
   `DATABASE_URL`, `VAPI_API_KEY`, `OPENROUTER_API_KEY`, `DEMO_USER_PASSWORD` (`SECRET_KEY` and
   `VAPI_WEBHOOK_SECRET` are generated).
3. First boot: migrations → seed → Vapi sync (assistant now points at the Render URL, number attached).
   The number is printed in the logs and shown on the dashboard Overview.
4. Keep-alive: a 5-minute monitor (UptimeRobot/cron-job.org) on `/api/v1/healthcheck` prevents Render's
   free-tier spin-down (a 30–60 s cold start would break a live call) and keeps the Supabase project active.

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | prod | Supabase session-pooler URI (`postgresql://…pooler.supabase.com:5432/postgres`). Defaults to SQLite locally. |
| `SECRET_KEY` | prod | JWT signing key for dashboard logins. |
| `OPENROUTER_API_KEY` | yes | LangChain → OpenRouter (conversation + analysis). |
| `LLM_MODEL` / `LLM_REASONING_EFFORT` / `LLM_PROVIDER_ORDER` | no | Model (`openai/gpt-oss-120b`), reasoning effort (`low`), preferred providers (`Cerebras,Groq`). |
| `VAPI_API_KEY` | yes | Vapi private key (assistant/number management). |
| `VAPI_WEBHOOK_SECRET` | yes | Shared secret Vapi presents to our endpoints (Bearer / `x-vapi-secret`). |
| `PUBLIC_BASE_URL` | local | Public origin of this server; Render's `RENDER_EXTERNAL_URL` is used automatically. |
| `VAPI_SYNC_ON_STARTUP`, `VAPI_AREA_CODE`, `VAPI_PHONE_NUMBER_ID`, `VAPI_ASSISTANT_ID`, `VAPI_VOICE_ID` | no | Assistant/number management knobs. |
| `SEED_DEMO_DATA`, `DEMO_USER_EMAIL`, `DEMO_USER_PASSWORD`, `ALLOW_SIGNUP` | no | Seed data + dashboard accounts. |
| `CLINIC_NAME`, `AGENT_NAME` | no | Persona used in the prompt and greeting. |

All secrets come from the environment; nothing is hard-coded. See `.env.example`.

---

## REST API

Envelope on every response: `{"data": …, "error": null}` or
`{"data": null, "error": {"code", "message", "details": [{"field", "message"}]}}`.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/patients?last_name=&date_of_birth=&phone_number=&q=&include_deleted=` | Soft-deleted rows excluded by default. DOB accepts `MM/DD/YYYY` or ISO; phone accepts any formatting. |
| `GET` | `/patients/{id}` | `404` when missing or soft-deleted, `422` on a malformed UUID. |
| `POST` | `/patients` | `201` + record; `422` with per-field errors; `400` on malformed JSON. |
| `PUT` | `/patients/{id}` | Partial update (only provided fields change), re-validated. |
| `DELETE` | `/patients/{id}` | Soft delete → `{"patient_id", "deleted_at"}`. |
| `POST/POST/GET` | `/api/v1/auth/signup` · `/login` · `/me` | Dashboard JWT auth. |
| `GET` | `/api/v1/calls`, `/api/v1/calls/{id}`, `/api/v1/patients/{id}/calls` | Transcripts, captures, analysis, recording URL (JWT). |
| `GET` | `/api/v1/dashboard/status` · `/stats` | Liveness + live call (public) · tiles + recent registrations (JWT). |
| `POST` | `/api/v1/voice/chat/completions` · `/webhook` | Vapi endpoints (shared secret). |
| `GET` | `/api/v1/healthcheck` · `/api/v1/logs` | health check + JSON log viewer. |

```bash
curl -X POST $API/patients -H 'Content-Type: application/json' -d '{
  "first_name":"Jane","last_name":"Doe","date_of_birth":"03/14/1987","sex":"Female",
  "phone_number":"(212) 555-0188","address_line_1":"44 Bleecker St","city":"New York","state":"NY","zip_code":"10012"}'
curl "$API/patients?last_name=Doe"
```

### Data model

`patients` stores the spec's fields with database-level constraints: NOT NULL on required fields, length
CHECKs, `sex` enum CHECK, 10-digit phone (Postgres regex CHECK `^[2-9]\d{2}[2-9]\d{6}$`), ZIP / ZIP+4
regex, 2-letter state, DOB not in the future, indexes on `last_name`, `date_of_birth`, `phone_number`,
`deleted_at`, UTC `created_at`/`updated_at` (trigger + ORM), `deleted_at` for soft delete. Phone is
deliberately **not unique** (family members share numbers); duplicate detection is a lookup instead.
`calls` keeps one row per Vapi call: live stage, draft fields, capture events, transcript, recording URL,
outcome (`registered | updated | partial | failed`) and the post-call analysis. `users` holds dashboard
logins (argon2). Schema: `alembic/versions/0001_initial.py` (readable mirror in `db/schema.sql`). RLS is
enabled on all tables so Supabase's auto-generated REST API cannot expose patient data.

### Validation rules (`modules/patients/validators.py`)

Single source of truth for both the API and the voice tools: names 1–50 letters plus hyphen/apostrophe
(internal spaces allowed for "Mary Ann" — a documented relaxation); DOB `MM/DD/YYYY` or ISO, real date,
not in the future, after 1900; sex enum with spoken aliases ("prefer not to say" → *Decline to Answer*);
phone → 10 NANP digits from any formatting; email via `email-validator` (spoken "jane dot doe at gmail dot
com" works); state names → abbreviations; ZIP `^\d{5}(-\d{4})?$`; member id alphanumeric; language defaults
to English.

---

## The voice agent

* **Prompt:** `modules/voice/prompts/system_prompt.md` — annotated with HTML comments (stripped before
  sending) explaining each section: voice style, collection order, number-speaking rules, spelling and
  corrections, out-of-order answers, interruptions, the optional-fields wording from the spec, read-back
  confirmation, failure scripts, start-over, Spanish.
* **Tools:** `modules/voice/tools.py` — LangChain `StructuredTool`s with pydantic schemas. Tools never
  raise: `{"ok": true, …}`, `{"ok": false, "errors": {field: msg}}` (agent fixes with the caller) or
  `{"ok": false, "error": "…"}` (agent apologises). `capture_fields` also records per-turn capture events,
  corrections (a field captured again with a new value) and the live stage shown on the dashboard.
* **Loop placement:** default `VOICE_LLM_MODE=vapi` — Vapi calls the model (OpenRouter) and our tools via
  the `tool-calls` webhook. `VOICE_LLM_MODE=custom` — `modules/voice/agent.py` runs the loop in LangChain
  (`ChatOpenAI(base_url=openrouter).bind_tools(...)`, streams tokens, runs tools in-process, emits Vapi's
  `endCall`); the LLM is injectable, so the loop is tested with a scripted fake model.
* **Assistant config as code:** `modules/voice/assistant_config.py` (voice, transcriber, greeting, model +
  prompt + tool schemas, webhook + secret, `endCallPhrases`, recording, silence/max-duration limits, 60 s
  tool timeouts with a spoken "One moment…").
* **Post-call analysis & Q&A:** `modules/analysis/analysis_service.py` — LangChain structured output
  (`CallAnalysis`: summary, extracted fields, corrections, validation re-prompts, completion, sentiment) and
  `ask_about_call()` behind `POST /api/v1/calls/{id}/ask` (the "Ask about this call" box on the Transcript
  screen).

---

## Edge cases & resilience

| Scenario | Behaviour |
|---|---|
| Invalid DOB / phone / ZIP / state | `capture_fields` returns a field-specific error → agent re-prompts for that field only; the API rejects the same values with `422`. |
| Caller corrects a value ("D-O-E, not Davies") | Agent re-captures; the correction is recorded and highlighted in the transcript. |
| Out-of-order / multiple answers at once | Prompt: accept everything given, never re-ask. |
| Caller wants to start over | `capture_fields(reset=true)` clears the draft; conversation restarts at the name. |
| Existing patient (same phone) | Offered an update instead of a duplicate (`update_patient`). |
| Database write fails | Tool returns `ok:false` → agent retries once, then apologises and ends the call; call marked `failed`. Never silence. |
| LLM/OpenRouter error | The stream always emits a spoken fallback line; the turn is logged. |
| Telephony drops mid-call | Vapi's end-of-call report marks the call `partial`; the draft fields already captured are kept and shown as a *Partial* row. |
| Render cold start | Only a tool call waits (60 s timeout + "One moment…"), never the conversation itself; keep-alive ping recommended; stale in-progress calls auto-close after 20 min. |
| Webhook/endpoint abuse | Shared secret required (`x-vapi-secret` / Bearer), constant-time compare. |

Logging: JSON lines to stdout and `logs/` (structured logger) — every turn, tool call with arguments and
result, the **final saved payload** (`call.completed`), and the end-of-call summary.

---

## Known limitations / trade-offs

* **Why the loop runs in Vapi.** A voice turn has about a second before it stops feeling like conversation;
  Vapi meets it by pipelining STT → LLM streaming → TTS on co-located infrastructure and cancelling on
  barge-in. Routing every turn through Render → OpenRouter adds serial hops, doubles the cost of tool
  turns, and turns a Render cold start into a dead call — so our code lives on the tool path. The custom
  LangChain loop is kept (`VOICE_LLM_MODE=custom`, tested) for full control when latency matters less.
* **Vapi + OpenRouter tool calling** depends on the upstream provider honouring function calls for
  `gpt-oss-120b`; if a call misbehaves, `VAPI_MODEL_PROVIDER=openai` + `VAPI_MODEL=gpt-4o` is a one-line
  switch (billed from Vapi credit).
* **Free tiers.** Render spins idle services down; Supabase pauses projects after 7 idle days; a free Vapi
  number supports U.S. area codes only.
* **Transcript fidelity.** The live transcript is rebuilt from the history Vapi sends each turn and replaced
  by Vapi's final transcript at the end of the call; per-turn "extracted" chips come from tool calls, so a
  turn where the model did not call `capture_fields` shows no chips.
* **Names.** Spaces are accepted inside names (spec says letters/hyphens/apostrophes); accented letters are
  accepted too.
* **Phone uniqueness** is not enforced (shared family phones); duplicate detection is advisory.
* **Appointment scheduling** is a deterministic mock (no real calendar). **Spanish** relies on the prompt and
  Deepgram `nova-3`; set `transcriber.language` to `multi` in `assistant_config.py` for code-switching.
* Signup is open by default (`ALLOW_SIGNUP=false` to disable).

## Next steps

Streaming the live transcript to the dashboard over SSE instead of polling, SMS confirmation after
registration, real scheduling integration, per-field confidence from Deepgram to trigger spell-backs,
and a Vapi web-call button on the dashboard for keyless testing.

