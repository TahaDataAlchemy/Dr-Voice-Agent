# Voice AI Agent — Patient Registration (Submission)

A voice AI agent on a real U.S. phone number that registers patients through natural conversation,
validates and persists their demographics to a database, and exposes them via a REST API and a dashboard.

## Live demo

| | |
|---|---|
| 📞 **Call the agent** | **+1 (843) 969-4283** |
| 🌐 **API base URL** | https://dr-voice-agent--tahamehboob281.replit.app |
| 🖥️ **Dashboard** | https://dr-voice-agent--tahamehboob281.replit.app/app |
| 🔑 **Dashboard login** | `demo@example.com` / `demo12345` |
| 📚 **API docs (OpenAPI)** | https://dr-voice-agent--tahamehboob281.replit.app/docs |
| 💻 **Repository** | https://github.com/TahaDataAlchemy/Dr-Voice-Agent |

## How to test

**By phone (the main flow):** call **+1 (843) 969-4283** and speak naturally. The agent collects your
name, phone, city (required) and optionally date of birth, sex, address, insurance, emergency contact and
language, reads everything back for confirmation, then saves the record and says "You're all set." Try a
correction ("it's D-A-V-I-S, not Davies") or an invalid value (a future birth year) — it re-prompts for just
that field.

**By API:**
```bash
BASE=https://dr-voice-agent--tahamehboob281.replit.app

# list patients
curl "$BASE/patients"

# create one
curl -X POST "$BASE/patients" -H "Content-Type: application/json" -d '{
  "first_name":"Jane","last_name":"Doe","phone_number":"(212) 555-0188","city":"New York"}'

# filter
curl "$BASE/patients?last_name=Doe"
```

**By dashboard:** open the dashboard link, log in with the demo account, and browse **Overview** (live call +
stats), **Patients**, **Record**, and **Transcript** (the full call conversation with the fields extracted
each turn).

## What it does

- **Natural voice conversation** — collects the standard U.S. patient demographics, understands varied
  phrasing, handles corrections and out-of-order answers, and confirms everything before saving.
- **Server-side validation** — names, dates (not in the future), 10-digit U.S. phones, states, ZIP codes,
  etc. are validated both by the agent and again by the API.
- **Persistence** — records are saved to Postgres and survive restarts; a second call with the same phone
  number is recognized and offered an update instead of a duplicate.
- **REST API** — `GET/POST /patients`, `GET/PUT/DELETE /patients/{id}` with filters, consistent JSON
  envelope, and soft delete.
- **Dashboard** — login, live call banner, patient roster, patient records, and call transcripts with a
  post-call summary and an "ask about this call" chat.

## Tech stack

| Layer | Technology |
|---|---|
| Telephony / speech | **Vapi** (phone number, Deepgram STT, TTS, turn-taking, recording) |
| Conversation model | **GPT-4o** (run by Vapi) with our prompt + tools |
| Analysis / chat | **Groq `gpt-oss-120b`** via LangChain (post-call summary + Q&A) |
| Backend | **FastAPI** (Python 3.11), REST API + Vapi webhook + JWT auth |
| Database | **Supabase Postgres** (SQLModel + Alembic migrations) |
| Dashboard | **Next.js + Tailwind**, served by the backend at `/app` |
| Hosting | **Replit** (backend + dashboard) + **Supabase** (database) |

## Notes

- No real patient data is stored; seed data is fictional.
- Detailed request flows, endpoint reference and screen-by-screen docs are in the repository
  (`docs/ARCHITECTURE.md`).
