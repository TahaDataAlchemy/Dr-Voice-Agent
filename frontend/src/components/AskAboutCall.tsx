"use client";

import clsx from "clsx";
import { Loader2, MessageCircleQuestion, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiRequestError } from "@/lib/api";
import { Card } from "./ui";

interface Turn {
  role: "user" | "assistant";
  content: string;
}

const SUGGESTIONS = [
  "What did the caller correct?",
  "Was anything rejected by validation?",
  "Summarize this call in two sentences.",
  "Did the caller sound frustrated?",
];

/** "Ask about this call" - LangChain answers from the stored transcript + captures (POST /api/v1/calls/{id}/ask). */
export function AskAboutCall({ callId, llmConfigured, model }: { callId: string; llmConfigured: boolean; model?: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns, busy]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setError(null);
    setQuestion("");
    const history = turns;
    setTurns((t) => [...t, { role: "user", content: q }]);
    setBusy(true);
    try {
      const res = await api<{ answer: string; model: string }>(`/api/v1/calls/${callId}/ask`, {
        method: "POST",
        body: JSON.stringify({ question: q, history }),
      });
      setTurns((t) => [...t, { role: "assistant", content: res.answer }]);
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.error.message : "Could not reach the API.");
      setTurns((t) => t.slice(0, -1));
      setQuestion(q);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <MessageCircleQuestion className="h-4 w-4 text-accent-text" /> Ask about this call
        </div>
        <span className="text-xs text-muted">{llmConfigured ? `LangChain · ${model ?? "OpenRouter"}` : "LLM not configured"}</span>
      </div>

      {turns.length === 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              disabled={!llmConfigured || busy}
              onClick={() => ask(s)}
              className="rounded-full border border-border bg-card px-3 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {turns.length > 0 && (
        <div className="mt-3 max-h-80 space-y-2 overflow-y-auto pr-1">
          {turns.map((t, i) => (
            <div key={i} className={clsx("flex", t.role === "user" ? "justify-end" : "justify-start")}>
              <div
                className={clsx(
                  "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
                  t.role === "user" ? "bg-accent-soft text-gray-900" : "bg-gray-100 text-gray-900",
                )}
              >
                {t.content}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex items-center gap-2 text-xs text-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> thinking…
            </div>
          )}
          <div ref={bottom} />
        </div>
      )}

      {error && <div className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger-text">{error}</div>}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="mt-3 flex items-center gap-2"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={!llmConfigured || busy}
          placeholder={llmConfigured ? "e.g. Which fields were captured before the caller hung up?" : "Set OPENROUTER_API_KEY to enable"}
          className="flex-1 rounded-xl border border-border bg-card px-4 py-2.5 text-sm placeholder:text-gray-400 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!llmConfigured || busy || !question.trim()}
          aria-label="Ask"
          className="rounded-xl border border-accent bg-accent p-2.5 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Send className="h-4 w-4" />
        </button>
      </form>
    </Card>
  );
}
