"use client";

import { Loader2, Play } from "lucide-react";
import { useState } from "react";
import { endpoints } from "@/lib/api";

/**
 * Resolves a call's recording through the backend (which signs it with the Vapi key server-side),
 * then plays it. Vapi recordings live in a private bucket, so we can't point <audio> at the raw URL.
 */
export function RecordingPlayer({ callId, hasRecording }: { callId: string; hasRecording: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await endpoints.recordingUrl(callId);
      setUrl(res.url);
    } catch {
      setError("Recording isn't available for this call.");
    } finally {
      setLoading(false);
    }
  }

  if (!hasRecording) return null;
  if (url) return <audio controls autoPlay src={url} className="mt-3 w-full" />;

  return (
    <div className="mt-3">
      <button
        onClick={load}
        disabled={loading}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3.5 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-60"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
        Load recording
      </button>
      {error && <span className="ml-2 text-xs text-muted">{error}</span>}
    </div>
  );
}
