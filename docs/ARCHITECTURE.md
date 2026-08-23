# Architecture & Screen Flows — Patient Voice Agent

A voice AI agent on a real U.S. phone number that registers patients through natural conversation,
persists them to Postgres, and exposes them through a REST API and a dashboard. This document covers the
tech stack, the system flow, and every dashboard screen with its navigation.

---

## Tech stack

| Layer | Technology | Role |
|---|---|---|
| Telephony / STT / TTS | **Vapi** | Provides the phone number, speech-to-text (Deepgram nova‑3), the TTS voice, turn-taking and barge-in. Runs the per-turn conversation loop using **our** system prompt and **our** tool definitions. |
| Conversation LLM | **OpenRouter · `openai/gpt-oss-120b`** | The model Vapi calls each turn (swappable via env; Vapi-billed GPT‑4o is a one-line fallback). |
| Analysis / Q&A | **LangChain** (`langchain-openai` → OpenRouter) | Post-call structured analysis (summary, corrections, sentiment) and the "Ask about this call" chat. |
| Backend | **FastAPI** (Python 3.11, `uv`) | REST API, Vapi webhook, custom-LLM SSE endpoint, JWT auth, dashboard data. Modular `core/` + `modules/<feature>/` layout. |
| ORM / DB | **SQLModel + Alembic** on **Supabase Postgres** | Typed models, real constraints (NOT NULL, CHECK, regex), migrations. SQLite for tests. |
| Dashboard | **Next.js 16 + TypeScript + Tailwind + TanStack Query** | Static export served by FastAPI at `/app`. Polls the API for the live-call view. |
| Hosting | **Render** (Docker) + **Supabase** | One free web service (API + built UI); Supabase hosts the database. Local dev exposed to Vapi via **ngrok / cloudflared**. |
| Auth | **Custom JWT** (argon2 via `pwdlib`, `pyjwt`) | Dashboard login; the REST `/patients` API is public per the spec. |

---

## System flow

```
 Caller ──PSTN──▶  Vapi  (number · Deepgram STT · TTS · turn-taking · barge-in · recording)
                    │      runs the LLM loop with our prompt + tools → OpenRouter gpt-oss-120b
                    │
                    │  tool-calls / status / transcript / end-of-call-report   (HTTPS, x-vapi-secret)
                    ▼
      ┌──────────────────── FastAPI backend (Render / local+ngrok) ───────────────────┐
      │  modules/voice      webhook dispatcher · tools · assistant config              │
      │  modules/patients   validators · PatientService · REST /patients               │
      │  modules/calls      live call state · transcript · captures · outcome          │
      │  modules/analysis   LangChain post-call analysis + "ask about this call"       │
      │  modules/auth       JWT signup / login                                         │
      │  modules/dashboard  /status (public) · /stats (JWT)                            │
      │  static/            Next.js dashboard served at /app                           │
      └───────────────────────────────┬───────────────────────────────┬──────────────┘
                                      ▼                               ▼
                          Supabase Postgres                   OpenRouter (LLM)
                        (users · patients · calls)      (conversation + analysis)
```

**Division of labour.** Vapi owns the timing-critical audio loop (so voice latency stays low and
interruptions work). Our backend owns the logic and the data: it defines the prompt and tools, validates and
persists every field, and serves the API and dashboard. During a call, Vapi calls our webhook only when the
agent invokes a tool (`capture_fields`, `register_patient`, …) — a place where a short pause is natural.

### Call → data flow (one call)

1. **Call starts.** Vapi speaks the greeting and sends `status-update` → a `calls` row is created
   (`in_progress`, stage "Collecting name").
2. **Each turn.** The caller speaks → Deepgram transcribes → Vapi's LLM (our prompt) decides what to say and
   which tool to call. `transcript` events stream into `calls.messages` (the bubbles you see).
3. **Field capture.** After each answer the agent calls **`capture_fields`** → our validators normalize the
   value and store it on the call's draft; invalid values return a field-specific error so the agent
   re-asks only that field; a matching phone returns `existing_patient` → the agent offers an update.
4. **Save.** After the read-back confirmation the agent calls **`register_patient`** (or `update_patient`) →
   validated again server-side → written to Postgres → the call is marked `registered`/`updated`.
5. **End.** "You're all set… take care, goodbye." → Vapi's `endCall`. The `end-of-call-report` finalizes the
   call (transcript, recording, duration, outcome) and triggers the **LangChain analysis** in the background.

---

## Dashboard screens

The dashboard is a single-page app under **`/app`**. Login stores a JWT in the browser; every screen reads
the API with it. Navigation is the pill bar **Overview · Patients · Record · Transcript** plus a "…" menu
(email, API docs, sign out).

### Screen map

```
        ┌────────────┐        ┌────────────┐
        │   Login    │───────▶│  Overview  │◀── default after login
        └────────────┘        └─────┬──────┘
              ▲                      │ click a recent registration
        ┌─────┴──────┐              ▼
        │   Signup   │        ┌────────────┐   click patient    ┌────────────┐
        └────────────┘        │  Patients  │───────────────────▶│   Record   │
                              └─────┬──────┘  (also primes their └─────┬──────┘
                                    │          latest call)             │ View transcript →
                          click a "Partial" call                        ▼
                                    │                            ┌────────────┐
                                    └───────────────────────────▶│ Transcript │
                                                   ◀── back arrow │  (+ list)  │
                                                                  └────────────┘
```

### 1. Login / Signup — `/app/login`, `/app/signup`
Email + password. On success a JWT is stored and you land on Overview. Signup adds an optional full name and
shows inline field errors. Demo login: `demo@example.com` / `demo12345`.

### 2. Overview — `/app`
The at-a-glance screen. Polls `/dashboard/status` (4s) and `/dashboard/stats` (5s).
- **Live banner** — a green "Call in progress — (843) 969‑4283 · Collecting address · 02:14 elapsed" banner
  appears while a call is active, with a ticking timer.
- **Stat tiles** — Patients registered · Calls today · Completion rate · Avg call length.
- **Recent registrations** — last calls with avatar, phone, and an outcome badge
  (**Saved** / **Matched** / **In call** / **Partial** / **Failed**). Clicking a row opens the patient's
  **Record** (if saved) or the **Transcript** (if not).

### 3. Patients — `/app/patients`
The searchable roster. Loads all patients (incl. soft-deleted) + recent calls.
- **Search** by name, phone or DOB (instant, digit-aware) with a clear button.
- **Rows** show `DOB · phone · insurance` with an **Active** / **Deleted** badge.
- **Partial rows** — calls that ended before a record was saved appear here (amber **Partial**) and open the
  **Transcript**.
- Clicking a patient opens their **Record** *and* remembers their latest call, so the **Transcript** tab
  then shows that person's conversation.

### 4. Record — `/app/record?id=<patient_id>`
The full patient card. Loads `/patients/{id}` and the patient's calls.
- Header: initials, name, UUID, Active/Deleted badge.
- Four groups: **Demographics · Address · Insurance · Emergency contact**.
- **Edit** → modal that PUTs only changed fields, with inline `422` validation errors.
- **Play call** → plays the linked call's recording. **Soft delete** → confirm → `DELETE` (sets `deleted_at`).
- **View transcript →** jumps to that patient's latest call. Footer: created/updated in UTC.

### 5. Transcript — `/app/transcript`
The conversation view — two modes:
- **Calls list** (`/app/transcript?list=1`, or when nothing is selected): recent calls with name, phone,
  outcome badge and time. If a patient is selected, it's filtered to their calls with a "Show all calls"
  toggle. This is the **back-arrow target**, so you can jump between anyone's calls.
- **Transcript detail** (`/app/transcript?id=<call_id>`): the chat between Sam and the caller — assistant
  bubbles left, caller right. Turns where the agent re-prompted after a bad value or a correction are
  highlighted **amber**. Under each answer, **"Extracted this turn"** chips show the fields captured
  (`first_name: Jane`, `dob: 1987-03-14`, `dob: invalid`, "1 correction"). A **← back arrow** returns to the
  list. Below: a **Call details** card (caller, outcome, recording player, summary, sentiment, patient link)
  and **Ask about this call** — a chat box where LangChain answers questions from the stored transcript.

---

## API surface (summary)

Envelope on every response: `{"data": …, "error": null}` or `{"data": null, "error": {code, message, details}}`.

| Area | Endpoints |
|---|---|
| Patients (spec, public) | `GET/POST /patients` · `GET/PUT/DELETE /patients/{id}` (filters: `last_name`, `date_of_birth`, `phone_number`, `q`, `include_deleted`) |
| Auth | `POST /api/v1/auth/signup` · `/login` · `GET /api/v1/auth/me` |
| Calls (JWT) | `GET /api/v1/calls` · `/calls/{id}` · `POST /api/v1/calls/{id}/ask` · `GET /api/v1/patients/{id}/calls` |
| Dashboard | `GET /api/v1/dashboard/status` (public) · `/stats` (JWT) |
| Voice (Vapi, shared secret) | `POST /api/v1/voice/webhook` · `POST /api/v1/voice/chat/completions` |
| Ops | `GET /api/v1/healthcheck` · `/api/v1/logs` · OpenAPI at `/docs` |

---

## Data model (Supabase Postgres)

- **patients** — the standard U.S. demographic dataset with DB-level constraints (NOT NULL on required
  fields; CHECK for the `sex` enum, 10-digit phone, ZIP/ZIP+4, 2-letter state, DOB not in the future),
  UTC `created_at`/`updated_at`, and `deleted_at` for soft delete. Indexed on `last_name`, `date_of_birth`,
  `phone_number`.
- **calls** — one row per Vapi call: `stage`, `draft` (captured fields), `captures` (per-turn events),
  `messages` (transcript), `analysis`, `outcome` (registered/updated/partial/failed), recording URL,
  timings.
- **users** — dashboard logins (argon2 hashes).

Row-Level Security is enabled on all tables so Supabase's auto-generated REST API can't expose the data; the
app connects as the `postgres` role through the session pooler.
