# Patient Voice Agent — Project Documentation

A voice AI agent, reachable on a real U.S. phone number, that registers new patients through a natural
spoken conversation. It collects and validates standard U.S. demographic information, confirms it back to
the caller, saves it to a database, and exposes everything through a REST API and a web dashboard.

---

## 1. Live demo

| | |
|---|---|
| 📞 **Call the agent** | **+1 (843) 969-4283** |
| 🌐 **API base URL** | https://dr-voice-agent--tahamehboob281.replit.app |
| 🖥️ **Dashboard** | https://dr-voice-agent--tahamehboob281.replit.app/app |
| 🔑 **Dashboard login** | `demo@example.com` / `demo12345` |
| 📚 **API docs (OpenAPI/Swagger)** | https://dr-voice-agent--tahamehboob281.replit.app/docs |
| 💻 **Source code** | https://github.com/TahaDataAlchemy/Dr-Voice-Agent |

> No real patient data is stored — all seed and test data is fictional.

---

## 2. What it does, in one paragraph

A caller dials the number and speaks with "Sam," an intake coordinator. Sam asks for the caller's name,
phone and city (the required fields), then offers to also capture date of birth, sex, address, email,
insurance, emergency contact and preferred language. Sam understands varied phrasing, spells names back,
fixes corrections ("it's D‑A‑V‑I‑S, not Davies"), and re-asks for any value that fails validation (for
example a birth date in the future or a phone number that isn't ten digits). Before saving, Sam reads
everything back and asks for confirmation. On confirmation the record is written to Postgres, Sam says
"You're all set," and the call ends. Clinic staff can then see the patient — and the full call transcript —
on the dashboard, or query it through the REST API.

---

## 3. How a call works (end to end)

```
 Caller ──📞 PSTN──▶  Vapi  ──HTTPS──▶  FastAPI backend  ──▶  Supabase Postgres
                       │                     │
              speech⇄text, voice,      validates + saves,
              turn-taking, the LLM      serves API + dashboard
```

1. **Call connects.** Vapi answers and Sam speaks the greeting.
2. **Listening & speaking.** Vapi transcribes the caller's speech (Deepgram), decides what to say using the
   LLM (GPT‑4o) with our system prompt, and speaks the reply (TTS). This turn-by-turn loop runs on Vapi's
   infrastructure so the conversation stays fast and interruptible.
3. **Capturing fields.** Each time the caller gives information, the LLM calls our **`capture_fields`** tool.
   That request hits our backend, which **validates and normalizes** the value (e.g. "March 14th, 1987" →
   `1987-03-14`, "(212) 555‑0188" → `2125550188`) and remembers it for this call. If a value is invalid, the
   backend returns a specific error and Sam re-asks for just that field.
4. **Duplicate check.** When a phone number is captured, the backend checks for an existing patient with that
   number. If found, Sam offers to *update* the existing record instead of creating a duplicate.
5. **Confirmation & save.** Sam reads the collected details back and asks "Is everything correct?" On "yes,"
   the LLM calls **`register_patient`**; the backend validates the full record again and writes it to Postgres.
6. **Goodbye.** Sam says "You're all set, [name]," and hangs up. Vapi sends an end-of-call report
   (transcript, recording, duration) which the backend stores, then runs a short post-call analysis
   (summary, corrections, sentiment) with an LLM.

Everything the caller said, every field extracted, and the final saved record are all viewable afterward on
the dashboard.

---

## 4. Architecture & technology choices

The system is split into clear layers, each doing one job:

| Layer | Technology | Why this choice |
|---|---|---|
| **Telephony + speech** | **Vapi** | Gives a real U.S. phone number and bundles speech-to-text, text-to-speech and turn-taking. It runs the timing-critical voice loop on its own infrastructure, which keeps latency low and interruptions natural — the hardest part to build well from scratch. |
| **Speech-to-text (STT)** | **Deepgram `nova-3`** | Fast, accurate streaming transcription (configured through Vapi). |
| **Text-to-speech (TTS)** | **Vapi voice `Elliot`** | Natural built-in voice, no extra vendor needed. |
| **Conversation LLM** | **OpenAI `gpt-4o`** (run by Vapi) | Reliable tool-calling and natural dialogue. Our prompt and tool definitions live in our code and are pushed to Vapi. |
| **Post-call analysis + "Ask about this call"** | **Groq `gpt-oss-120b`** via **LangChain** | Runs after the call, where latency doesn't matter; Groq's free tier keeps this at no cost. |
| **Backend / API** | **FastAPI** (Python 3.11) | Async, great for the streaming webhook, automatic OpenAPI docs, strong validation via Pydantic. |
| **Database + ORM** | **Supabase Postgres** with **SQLModel + Alembic** | A managed Postgres with real constraints and migrations; the data survives restarts. |
| **Dashboard** | **Next.js + Tailwind** | A small, modern SPA served by the backend itself at `/app`, so the whole thing is one deployable. |
| **Auth** | **Custom JWT** (argon2 password hashing) | Protects the dashboard; the public `/patients` API stays open per the spec so reviewers can curl it. |
| **Hosting** | **Replit** (backend + dashboard) + **Supabase** (database) | Free, no card required — see §9. |

**Key design principle — separation of concerns.** The telephony/speech layer (Vapi) is completely separate
from the conversation logic (our prompt + tools), which is separate from the data layer (validation +
database), which is separate from the API. The voice agent and the REST API both go through the **same
validation and the same service layer**, so a patient created by phone is validated identically to one
created by an API call — the API never blindly trusts the agent.

---

## 5. The voice agent

- **System prompt** (`modules/voice/prompts/system_prompt.md`) — a carefully written, commented prompt that
  defines Sam's persona, the order fields are collected, how to speak numbers and dates, how to handle
  spellings and corrections, out-of-order answers, interruptions, the confirmation read-back, what to do when
  a save fails, and how to start over. It's versioned in the repo, not hidden in a vendor dashboard.
- **Tools** (`modules/voice/tools.py`) — the actions the agent can take, each validated server-side:
  - `capture_fields` — validate and store one or more fields (and detect duplicates by phone).
  - `lookup_patient_by_phone` — check whether a caller is already registered.
  - `register_patient` / `update_patient` — save a new record or update an existing one.
  - `schedule_appointment` — book a first appointment (mock scheduler, a bonus feature).
  - `end_call` — hang up gracefully after the goodbye.
  - Tools never crash the call: any problem comes back as a friendly message the agent relays, never silence.
- **Validation** (`modules/patients/validators.py`) — the single source of truth for the rules: names,
  dates (real date, not in the future), 10-digit U.S. phone numbers, U.S. states, ZIP/ZIP+4, email, etc. It
  even understands spoken forms like "jane dot doe at gmail dot com."

---

## 6. Data model

A patient record has the standard U.S. demographic fields. **Required:** first name, last name, phone, city.
**Optional (collected if the caller opts in):** date of birth, sex, street address, state, ZIP, email,
insurance provider + member ID, emergency contact name + phone, preferred language. Every record also has an
auto-generated UUID, UTC created/updated timestamps, and a soft-delete flag.

The database enforces this with real constraints (NOT NULL on required fields, a CHECK on the `sex` values,
regex checks on phone/ZIP/state on Postgres) — so the data stays clean even if something bypassed the app.
Each phone call is also stored as a `calls` record with its transcript, the fields captured, the outcome
(registered / updated / partial / failed) and the post-call analysis.

---

## 7. REST API

Every response uses a consistent envelope: `{"data": …, "error": null}` on success, or
`{"data": null, "error": {code, message, details}}` on failure, with correct HTTP status codes.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/patients` | List patients. Filters: `?last_name=`, `?date_of_birth=`, `?phone_number=` (plus free-text `?q=`). |
| `GET` | `/patients/{id}` | Get one patient by UUID. |
| `POST` | `/patients` | Create a patient (returns the created record). |
| `PUT` | `/patients/{id}` | Update a patient (partial updates allowed). |
| `DELETE` | `/patients/{id}` | Soft-delete (sets `deleted_at`; the record is retained). |

Example:
```bash
BASE=https://dr-voice-agent--tahamehboob281.replit.app
curl "$BASE/patients?last_name=Doe"
curl -X POST "$BASE/patients" -H "Content-Type: application/json" \
  -d '{"first_name":"Jane","last_name":"Doe","phone_number":"(212) 555-0188","city":"New York"}'
```

Interactive docs (try every endpoint in the browser): **`/docs`**.

---

## 8. The dashboard

A clean web dashboard (login required) with four screens:

- **Overview** — a live "call in progress" banner while someone is on the phone, headline stats (patients
  registered, calls today, completion rate, average call length) and a list of recent registrations.
- **Patients** — a searchable roster (by name, phone or date of birth) with active/deleted status. Calls
  that ended before completing show as "partial."
- **Record** — the full patient card (demographics, address, insurance, emergency contact) with edit,
  soft-delete and "play call recording."
- **Transcript** — the actual conversation between Sam and the caller, shown as chat bubbles, with the
  fields extracted on each turn, corrections highlighted, a post-call summary, and an **"Ask about this
  call"** chat box that answers questions about the call using the stored transcript.

---

## 9. Edge cases & resilience

The system is built to handle things going wrong:

- **Invalid input** (future birth date, 3-digit phone, unknown state, bad ZIP) → the agent re-prompts for
  exactly that field; the API rejects the same values with a `422` and a field-specific message.
- **Corrections & out-of-order answers** → captured and re-read back; the caller can also say "start over."
- **Returning caller** → recognized by phone number and offered an update instead of a duplicate.
- **A save that fails** → the caller hears an apology and a retry, never silence; the call is marked failed.
- **The caller hangs up mid-call** → the partial data is kept and shown as a "partial" registration.
- **Security** → the Vapi webhook is protected by a shared secret; API keys live only in environment
  variables, never in the code.

---

## 10. Deployment & hosting notes

The backend and dashboard run as one service on **Replit**; the database is **Supabase Postgres**. This
combination was chosen deliberately: both have genuinely free tiers that **do not require a credit card**.
(During development I found that most "free" hosts — Render, Railway, Fly, Koyeb, Back4App's permanent URL —
now require a card for identity verification; Replit's free deployment did not, so the live demo runs there.)

On startup the app runs its database migrations, seeds demo data, and points the Vapi phone number at its own
public URL, so calling the number works without any machine of mine being on.

**Tech-stack justification in one line:** use the specialist platform for the hard real-time part (Vapi for
voice), keep the logic and data in clean, testable code (FastAPI + Postgres), and validate everything
server-side so the API is trustworthy on its own.

---

## 11. Known limitations & trade-offs

- **Free-tier hosting** means the app can sleep when idle and take a moment to wake on the first request after
  a quiet period.
- **Vapi free number** supports U.S. area codes and receives U.S. calls; international callers pay their
  carrier's international rate.
- **Call minutes** draw down a small Vapi credit (~$0.20–0.40/min); it is not a per-call charge to the caller.
- **Appointment scheduling** is a working mock (no real calendar integration).
- No real patient data is stored, and there is no HIPAA compliance — this is a technical demonstration.

---

*Prepared by Taha Mehboob. Full request-flow diagrams and a screen-by-screen reference are in the
repository under `docs/ARCHITECTURE.md`.*
