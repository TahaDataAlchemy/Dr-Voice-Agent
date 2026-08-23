"""
Voice layer tests with a scripted fake chat model:
  * secret enforcement on both Vapi endpoints
  * custom-LLM turn: tool calls executed in-process, SSE chunk shape, endCall tool emitted
  * capture_fields validation + duplicate detection + corrections bookkeeping
  * webhook: status-update / transcript / end-of-call-report finalize the call row
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

from modules.voice import routes as voice_routes
from modules.voice.agent import VoiceAgent
from tests.conftest import VAPI_HEADERS

CALL = {"id": "call-test-1", "type": "inboundPhoneCall", "customer": {"number": "+14155550139"}}


class ScriptedChatModel(GenericFakeChatModel):
    """Fake chat model that streams scripted AIMessages (supports tool calls) and accepts bind_tools."""

    def bind_tools(self, tools, **kwargs):  # noqa: D401 - behave like a tool-capable model
        return self

    async def _astream(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        message = next(self.messages)
        if isinstance(message, str):
            message = AIMessage(content=message)
        if message.tool_calls:
            chunk = AIMessageChunk(
                content=message.content,
                tool_call_chunks=[
                    {"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": i}
                    for i, tc in enumerate(message.tool_calls)
                ],
            )
            yield ChatGenerationChunk(message=chunk)
            return
        for token in message.content.split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=token + " "))


def scripted_agent(messages: list[Any]) -> VoiceAgent:
    return VoiceAgent(llm=ScriptedChatModel(messages=iter(messages)))


def _collect_sse(resp) -> tuple[list[dict[str, Any]], str]:
    chunks = []
    for line in resp.text.split("\n"):
        if line.startswith("data: ") and line != "data: [DONE]":
            chunks.append(json.loads(line[6:]))
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    return chunks, text


@pytest.fixture
def use_agent(monkeypatch):
    def _set(messages):
        agent = scripted_agent(messages)
        monkeypatch.setattr(voice_routes, "get_agent", lambda: agent)
        return agent

    return _set


def test_secret_required(client):
    assert client.post("/api/v1/voice/chat/completions", json={"messages": []}).status_code == 401
    assert client.post("/api/v1/voice/webhook", json={"message": {"type": "hang"}}).status_code == 401
    ok = client.post(
        "/api/v1/voice/webhook",
        json={"message": {"type": "hang"}},
        headers={"Authorization": "Bearer test-vapi-secret"},
    )
    assert ok.status_code == 200


def test_turn_streams_text_and_runs_tools(client, use_agent):
    use_agent(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "capture_fields", "args": {"first_name": "Jane", "last_name": "Davies"}}],
            ),
            "Thanks Jane. And what is the best phone number to reach you?",
        ]
    )
    body = {
        "model": "x",
        "stream": True,
        "call": CALL,
        "messages": [
            {"role": "system", "content": "ignored"},
            {"role": "assistant", "content": "Could I start with your name?"},
            {"role": "user", "content": "Jane Davies"},
        ],
    }
    resp = client.post("/api/v1/voice/chat/completions", json=body, headers=VAPI_HEADERS)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    chunks, text = _collect_sse(resp)
    assert "phone number" in text
    assert chunks[0]["object"] == "chat.completion.chunk"
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert resp.text.strip().endswith("data: [DONE]")

    # capture was persisted on the call row
    token = client.post("/api/v1/auth/login", json={"email": "demo@example.com", "password": "demo12345"}).json()["data"]["access_token"]
    calls = client.get("/api/v1/calls", headers={"Authorization": f"Bearer {token}"}).json()["data"]
    assert calls[0]["vapi_call_id"] == "call-test-1"
    assert calls[0]["draft"]["first_name"] == "Jane"
    assert calls[0]["stage"] == "Collecting phone number"
    assert calls[0]["status"] == "in_progress"
    assert calls[0]["caller_number"] == "+14155550139"


def test_validation_error_and_correction_bookkeeping(client, use_agent, auth_headers):
    use_agent(
        [
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "capture_fields", "args": {"date_of_birth": "03/14/2087"}}]),
            "That date is in the future, could you repeat your date of birth?",
        ]
    )
    base = {"call": CALL, "messages": [{"role": "user", "content": "March 14 2087"}]}
    resp = client.post("/api/v1/voice/chat/completions", json=base, headers=VAPI_HEADERS)
    assert "future" in _collect_sse(resp)[1]

    use_agent(
        [
            AIMessage(content="", tool_calls=[{"id": "c2", "name": "capture_fields", "args": {"last_name": "Davies", "date_of_birth": "03/14/1987"}}]),
            AIMessage(content="", tool_calls=[{"id": "c3", "name": "capture_fields", "args": {"last_name": "Doe"}}]),
            "Got it, Doe. Thanks.",
        ]
    )
    client.post("/api/v1/voice/chat/completions", json=base, headers=VAPI_HEADERS)
    call = client.get("/api/v1/calls", headers=auth_headers).json()["data"][0]
    assert call["draft"]["last_name"] == "Doe"
    assert call["draft"]["date_of_birth"] == "1987-03-14"
    assert call["corrections"] == 1
    detail = client.get(f"/api/v1/calls/{call['id']}", headers=auth_headers).json()["data"]
    assert detail["captures"][0]["errors"]["date_of_birth"].startswith("date of birth cannot be in the future")
    assert detail["captures"][-1]["corrections"] == [{"field": "last_name", "from": "Davies", "to": "Doe"}]


def test_duplicate_detection_and_update(client, use_agent, patient_payload, auth_headers):
    existing = client.post("/patients", json=patient_payload).json()["data"]
    use_agent(
        [
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "capture_fields", "args": {"phone_number": "415 555 0139"}}]),
            "It looks like we already have a record for Aisha Khan. Would you like to update your information instead?",
        ]
    )
    body = {"call": CALL, "messages": [{"role": "user", "content": "415 555 0139"}]}
    _, text = _collect_sse(client.post("/api/v1/voice/chat/completions", json=body, headers=VAPI_HEADERS))
    assert "already have a record for Aisha Khan" in text

    use_agent(
        [
            AIMessage(content="", tool_calls=[{"id": "c2", "name": "update_patient", "args": {"patient_id": existing["patient_id"], "city": "Oakland"}}]),
            "Done, your city is now Oakland. You're all set, Aisha. Take care, goodbye.",
            AIMessage(content="", tool_calls=[{"id": "c3", "name": "end_call", "args": {"reason": "completed"}}]),
        ]
    )
    # First turn: update; the scripted model then says goodbye (no tool call) -> turn ends.
    client.post("/api/v1/voice/chat/completions", json=body, headers=VAPI_HEADERS)
    assert client.get(f"/patients/{existing['patient_id']}").json()["data"]["city"] == "Oakland"
    call = client.get("/api/v1/calls", headers=auth_headers).json()["data"][0]
    assert call["outcome"] == "updated" and call["patient_id"] == existing["patient_id"]
    assert call["patient_name"] == "Aisha Khan"


def test_register_and_end_call_emits_endcall_tool(client, use_agent, patient_payload, auth_headers):
    use_agent(
        [
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "register_patient", "args": patient_payload}]),
            AIMessage(
                content="You're all set, Aisha. Take care, goodbye.",
                tool_calls=[{"id": "c2", "name": "end_call", "args": {"reason": "completed"}}],
            ),
        ]
    )
    body = {"call": {**CALL, "monitor": {"controlUrl": "http://127.0.0.1:9/control"}}, "messages": [{"role": "user", "content": "Yes, that's all correct"}]}
    resp = client.post("/api/v1/voice/chat/completions", json=body, headers=VAPI_HEADERS)
    chunks, text = _collect_sse(resp)
    assert "You're all set, Aisha" in text
    tool_chunks = [c for c in chunks if c["choices"][0]["delta"].get("tool_calls")]
    assert tool_chunks and tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "endCall"
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"

    patients = client.get("/patients", params={"phone_number": "4155550139"}).json()["data"]
    assert len(patients) == 1 and patients[0]["first_name"] == "Aisha"
    call = client.get("/api/v1/calls", headers=auth_headers).json()["data"][0]
    assert call["outcome"] == "registered" and call["patient_id"] == patients[0]["patient_id"]
    assert call["fields_captured"] == 16


def test_non_streaming_completion(client, use_agent):
    use_agent(["Sure, what is your first name?"])
    body = {"stream": False, "call": CALL, "messages": [{"role": "user", "content": "hi"}]}
    resp = client.post("/api/v1/voice/chat/completions", json=body, headers=VAPI_HEADERS)
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert "first name" in data["choices"][0]["message"]["content"]


def test_llm_failure_never_leaves_silence(client, monkeypatch):
    class Exploding(ScriptedChatModel):
        async def _astream(self, *a, **k):
            raise RuntimeError("openrouter down")
            yield  # pragma: no cover

    agent = VoiceAgent(llm=Exploding(messages=iter([])))
    monkeypatch.setattr(voice_routes, "get_agent", lambda: agent)
    body = {"call": CALL, "messages": [{"role": "user", "content": "hello"}]}
    _, text = _collect_sse(client.post("/api/v1/voice/chat/completions", json=body, headers=VAPI_HEADERS))
    assert "trouble" in text


def test_webhook_lifecycle_marks_partial_call(client, use_agent, auth_headers):
    use_agent([AIMessage(content="", tool_calls=[{"id": "c1", "name": "capture_fields", "args": {"first_name": "Tom", "last_name": "Nguyen"}}]), "Thanks Tom."])
    client.post("/api/v1/voice/chat/completions", json={"call": CALL, "messages": [{"role": "user", "content": "Tom Nguyen"}]}, headers=VAPI_HEADERS)

    status_msg = {"message": {"type": "status-update", "status": "in-progress", "call": CALL}}
    assert client.post("/api/v1/voice/webhook", json=status_msg, headers=VAPI_HEADERS).status_code == 200
    transcript = {"message": {"type": "transcript", "role": "user", "transcriptType": "final", "transcript": "Tom Nguyen", "call": CALL}}
    client.post("/api/v1/voice/webhook", json=transcript, headers=VAPI_HEADERS)

    status = client.get("/api/v1/dashboard/status").json()["data"]
    assert status["active_call"]["caller"] == "(415) 555-0139"
    assert status["active_call"]["stage"] == "Collecting phone number"
    assert status["webhook"]["last_type"] == "transcript"

    report = {
        "message": {
            "type": "end-of-call-report",
            "endedReason": "customer-ended-call",
            "durationSeconds": 42.4,
            "call": CALL,
            "artifact": {
                "recordingUrl": "https://example.com/rec.wav",
                "messages": [
                    {"role": "system", "message": "prompt"},
                    {"role": "bot", "message": "Could I start with your name?", "secondsFromStart": 1.2},
                    {"role": "user", "message": "Tom Nguyen", "secondsFromStart": 4.0},
                ],
            },
            "analysis": {"summary": "Caller hung up after giving their name."},
        }
    }
    assert client.post("/api/v1/voice/webhook", json=report, headers=VAPI_HEADERS).status_code == 200
    call = client.get("/api/v1/calls", headers=auth_headers).json()["data"][0]
    assert call["status"] == "ended" and call["outcome"] == "partial"
    assert call["duration_seconds"] == 42 and call["recording_url"].endswith("rec.wav")
    assert call["summary"].startswith("Caller hung up")
    assert call["patient_name"] == "Tom Nguyen"
    detail = client.get(f"/api/v1/calls/{call['id']}", headers=auth_headers).json()["data"]
    assert [m["role"] for m in detail["messages"]] == ["assistant", "user"]
    assert client.get("/api/v1/dashboard/status").json()["data"]["active_call"] is None

    stats = client.get("/api/v1/dashboard/stats", headers=auth_headers).json()["data"]
    assert stats["calls_today"] == 1 and stats["completion_rate"] == 0 and stats["recent"][0]["outcome"] == "partial"


# ---------------------------------------------------------------- Vapi-managed mode (tool-calls webhook)


def test_assistant_payload_vapi_mode_has_function_tools_and_prompt():
    from modules.voice.assistant_config import build_assistant_payload

    payload = build_assistant_payload("https://example.onrender.com")
    model = payload["model"]
    assert model["provider"] == "openrouter" and model["model"] == "openai/gpt-oss-120b"
    names = [t["function"]["name"] for t in model["tools"] if t.get("type") == "function"]
    assert names == ["lookup_patient_by_phone", "capture_fields", "register_patient", "update_patient", "schedule_appointment"]
    assert {"type": "endCall"} in model["tools"]
    capture = next(t for t in model["tools"] if t.get("type") == "function" and t["function"]["name"] == "capture_fields")
    assert capture["server"]["url"] == "https://example.onrender.com/api/v1/voice/webhook"
    assert capture["server"]["secret"] == "test-vapi-secret"
    assert "reset" in capture["function"]["parameters"]["properties"]
    prompt = model["messages"][0]["content"]
    assert "{{customer.number}}" in prompt and "Maple Health Clinic" in prompt and "`endCall`" in prompt
    assert payload["server"]["url"].endswith("/api/v1/voice/webhook")
    assert payload["endCallPhrases"]


def test_tool_calls_webhook_executes_tools_and_returns_results(client, auth_headers):
    call = {"id": "call-webhook-1", "type": "inboundPhoneCall", "customer": {"number": "+12125550188"}}
    artifact = {"messages": [
        {"role": "bot", "message": "Could I start with your first and last name?", "secondsFromStart": 1.0},
        {"role": "user", "message": "Jane Davies", "secondsFromStart": 3.5},
    ]}
    body = {
        "message": {
            "type": "tool-calls",
            "call": call,
            "artifact": artifact,
            "toolCallList": [
                {"id": "tc-1", "type": "function", "function": {"name": "capture_fields", "arguments": {"first_name": "Jane", "last_name": "Davies"}}},
            ],
        }
    }
    resp = client.post("/api/v1/voice/webhook", json=body, headers=VAPI_HEADERS)
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["toolCallId"] == "tc-1" and results[0]["name"] == "capture_fields"
    result = json.loads(results[0]["result"])
    assert result["ok"] is True and result["accepted"]["first_name"] == "Jane"

    # arguments may also arrive as a JSON string, and in the toolWithToolCallList shape
    body2 = {
        "message": {
            "type": "tool-calls",
            "call": call,
            "toolWithToolCallList": [
                {"name": "register_patient", "toolCall": {"id": "tc-2", "type": "function", "function": {"name": "register_patient", "arguments": json.dumps({
                    "first_name": "Jane", "last_name": "Doe", "date_of_birth": "03/14/1987", "sex": "female",
                    "phone_number": "212 555 0188", "address_line_1": "44 Bleecker St", "city": "New York", "state": "New York", "zip_code": "10012"})}}},
            ],
        }
    }
    resp = client.post("/api/v1/voice/webhook", json=body2, headers=VAPI_HEADERS)
    result = json.loads(resp.json()["results"][0]["result"])
    assert result["ok"] is True
    patients = client.get("/patients", params={"phone_number": "2125550188"}).json()["data"]
    assert patients[0]["last_name"] == "Doe" and patients[0]["state"] == "NY"

    detail = client.get("/api/v1/calls", headers=auth_headers).json()["data"][0]
    assert detail["vapi_call_id"] == "call-webhook-1" and detail["outcome"] == "registered"
    assert detail["caller_number"] == "+12125550188"
    full = client.get(f"/api/v1/calls/{detail['id']}", headers=auth_headers).json()["data"]
    assert [m["role"] for m in full["messages"]] == ["assistant", "user"]
    assert full["captures"][0]["turn_index"] == 2

    unknown = {"message": {"type": "tool-calls", "call": call, "toolCallList": [{"id": "x", "function": {"name": "nope", "arguments": {}}}]}}
    result = json.loads(client.post("/api/v1/voice/webhook", json=unknown, headers=VAPI_HEADERS).json()["results"][0]["result"])
    assert result["ok"] is False


def test_ask_about_call(client, auth_headers, monkeypatch):
    from langchain_core.messages import AIMessage as _AI

    from modules.analysis import analysis_service

    # create a call via the webhook path, then ask about it with a fake LLM
    call = {"id": "call-ask-1", "type": "inboundPhoneCall", "customer": {"number": "+12125550188"}}
    client.post("/api/v1/voice/webhook", json={"message": {"type": "tool-calls", "call": call, "toolCallList": [
        {"id": "t1", "function": {"name": "capture_fields", "arguments": {"first_name": "Jane", "date_of_birth": "03/14/2087"}}}]}}, headers=VAPI_HEADERS)
    row = client.get("/api/v1/calls", headers=auth_headers).json()["data"][0]

    resp = client.post(f"/api/v1/calls/{row['id']}/ask", json={"question": "Did anything get rejected?"}, headers=auth_headers)
    assert resp.status_code == 503  # no OPENROUTER_API_KEY in tests

    captured = {}

    class FakeLLM:
        def invoke(self, messages):
            captured["context"] = messages[1].content
            return _AI(content="Yes - the date of birth 03/14/2087 was rejected because it is in the future.")

    monkeypatch.setattr(analysis_service, "build_analysis_llm", lambda: FakeLLM())
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    from config import get_settings
    get_settings.cache_clear()
    try:
        resp = client.post(f"/api/v1/calls/{row['id']}/ask", json={"question": "Did anything get rejected?", "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}, headers=auth_headers)
    finally:
        monkeypatch.delenv("OPENROUTER_API_KEY")
        get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    assert "rejected" in resp.json()["data"]["answer"]
    assert "rejected date_of_birth" in captured["context"] and "first_name=Jane" in captured["context"]
    assert client.post(f"/api/v1/calls/{row['id']}/ask", json={"question": ""}, headers=auth_headers).status_code == 422
