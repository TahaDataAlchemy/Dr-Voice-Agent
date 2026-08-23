"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo } from "react";
import { AskAboutCall } from "@/components/AskAboutCall";
import { Shell } from "@/components/Shell";
import { Avatar, Badge, Card, Empty, Spinner, outcomeBadge } from "@/components/ui";
import { endpoints, type CallDetail, type CallSummary, type CaptureEvent } from "@/lib/api";
import { remember, useSelection } from "@/lib/auth";
import { formatDurationWords, formatPhone, shortId, timeAgo } from "@/lib/format";

export default function TranscriptPage() {
  return (
    <Shell title="Call transcript">
      <Suspense fallback={<Spinner />}>
        <TranscriptLoader />
      </Suspense>
    </Shell>
  );
}

function TranscriptLoader() {
  const params = useSearchParams();
  const selection = useSelection();
  const fromUrl = params.get("id");
  const showList = params.get("list") === "1"; // back arrow lands here
  const id = fromUrl ?? (showList ? null : selection.callId ?? null);
  useEffect(() => {
    if (fromUrl) remember({ callId: fromUrl }); // external system (localStorage) sync
  }, [fromUrl]);

  if (showList || !id) return <CallsList selectedPatientId={selection.patientId ?? null} />;
  return <Transcript id={id} backHref="/transcript?list=1" />;
}

/** List of recent calls (the "previous calls" the back arrow returns to). If a patient is
 *  selected, their calls are shown first with a toggle to show everyone's. */
function CallsList({ selectedPatientId }: { selectedPatientId: string | null }) {
  const params = useSearchParams();
  const showAll = params.get("all") === "1";
  const calls = useQuery({ queryKey: ["calls", "all"], queryFn: () => endpoints.calls(100), refetchInterval: 5000 });
  const patient = useQuery({
    queryKey: ["patient", selectedPatientId],
    queryFn: () => endpoints.patient(selectedPatientId!),
    enabled: Boolean(selectedPatientId),
  });

  if (calls.isLoading) return <Spinner />;
  const all = calls.data ?? [];
  const filtered =
    selectedPatientId && !showAll
      ? all.filter((c) => c.patient_id === selectedPatientId || c.matched_patient_id === selectedPatientId)
      : all;
  const who = patient.data ? `${patient.data.first_name} ${patient.data.last_name}` : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="text-base font-semibold">
          {selectedPatientId && !showAll && who ? `Calls for ${who}` : "Recent calls"}
        </div>
        {selectedPatientId && (
          <Link
            href={showAll ? "/transcript?list=1" : "/transcript?list=1&all=1"}
            className="text-sm text-accent-text hover:underline"
          >
            {showAll ? `Show ${who ?? "this patient"}'s calls` : "Show all calls"}
          </Link>
        )}
      </div>
      <Card>
        {filtered.length ? (
          <div className="row-divider">
            {filtered.map((c) => (
              <CallRow key={c.id} call={c} />
            ))}
          </div>
        ) : (
          <Empty>
            {selectedPatientId && !showAll
              ? "No calls linked to this patient yet."
              : "No calls yet. Transcripts appear here as soon as someone calls the agent."}
          </Empty>
        )}
      </Card>
    </div>
  );
}

function CallRow({ call }: { call: CallSummary }) {
  const badge = outcomeBadge(call.outcome, call.status);
  const name = call.patient_name ?? "Unknown caller";
  return (
    <Link
      href={`/transcript?id=${call.id}`}
      onClick={() => remember({ callId: call.id })}
      className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50"
    >
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{name}</div>
        <div className="truncate text-xs text-muted">
          {formatPhone(call.caller_number ?? call.draft.phone_number)} · Call {shortId(call.vapi_call_id)} ·{" "}
          {call.status === "in_progress" ? "in progress" : timeAgo(call.started_at)}
        </div>
      </div>
      <Badge tone={badge.tone}>{badge.label}</Badge>
    </Link>
  );
}

const LABEL: Record<string, string> = {
  first_name: "first_name",
  last_name: "last_name",
  date_of_birth: "dob",
  phone_number: "phone",
  address_line_1: "street",
  address_line_2: "unit",
  zip_code: "zip",
  insurance_provider: "insurer",
  insurance_member_id: "member_id",
  preferred_language: "language",
  emergency_contact_name: "emergency_name",
  emergency_contact_phone: "emergency_phone",
};

function Transcript({ id, backHref }: { id: string; backHref: string }) {
  const router = useRouter();
  const call = useQuery({
    queryKey: ["call", id],
    queryFn: () => endpoints.call(id),
    refetchInterval: (q) => (q.state.data?.status === "in_progress" ? 3000 : 15000),
  });

  const status = useQuery({ queryKey: ["status"], queryFn: endpoints.status, staleTime: 30000 });
  const layout = useMemo(() => (call.data ? buildLayout(call.data) : null), [call.data]);

  const back = (
    <button
      onClick={() => router.push(backHref)}
      className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100"
      aria-label="Back to calls"
      title="Back to calls"
    >
      <ArrowLeft className="h-5 w-5" />
    </button>
  );

  if (call.isLoading) return <Spinner />;
  if (call.isError || !call.data || !layout)
    return (
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2">
          {back}
          <span className="text-sm text-muted">Back to calls</span>
        </div>
        <Empty>Call not found.</Empty>
      </Card>
    );
  const c = call.data;
  const badge = outcomeBadge(c.outcome, c.status);
  const analysis = (c.analysis?.langchain ?? null) as null | { summary?: string; corrections?: unknown[]; sentiment?: string };
  const corrections = Math.max(c.corrections, analysis?.corrections?.length ?? 0);

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {back}
            <div className="text-base font-semibold">
              {c.patient_name ? `${c.patient_name} · ` : ""}Call {shortId(c.vapi_call_id)} ·{" "}
              {c.status === "in_progress" ? "live" : formatDurationWords(c.duration_seconds)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {c.status === "in_progress" && <Badge tone="green">Live</Badge>}
            <Badge tone="blue">{c.fields_captured} fields captured</Badge>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {layout.items.length === 0 && <Empty>Waiting for the first words…</Empty>}
          {layout.items.map((item, i) =>
            item.kind === "message" ? (
              <div key={i} className={clsx("flex", item.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={clsx(
                    "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                    item.role === "user"
                      ? "bg-accent-soft text-gray-900"
                      : item.highlight
                        ? "bg-warn-soft text-gray-900"
                        : "bg-gray-100 text-gray-900",
                  )}
                  title={item.highlight ? "Validation re-prompt or correction" : undefined}
                >
                  {item.content}
                </div>
              </div>
            ) : (
              <CaptureChips key={i} capture={item.capture} />
            ),
          )}
        </div>

        <div className="mt-5 border-t border-border pt-4">
          <div className="mb-2 text-xs text-muted">Extracted from this call</div>
          <div className="flex flex-wrap items-center gap-2">
            {Object.entries(c.draft).length === 0 && <span className="text-xs text-muted">nothing captured yet</span>}
            {Object.entries(c.draft).map(([k, v]) => (
              <span key={k} className="rounded-md bg-gray-100 px-2 py-1 font-mono text-xs text-gray-700">
                {LABEL[k] ?? k}: {String(v)}
              </span>
            ))}
            {corrections > 0 && (
              <Badge tone="amber">
                {corrections} correction{corrections === 1 ? "" : "s"}
              </Badge>
            )}
          </div>
        </div>
      </Card>

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-semibold">Call details</div>
          <Badge tone={badge.tone}>{badge.label}</Badge>
        </div>
        <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          <Row k="Caller" v={c.caller_number ? formatPhone(c.caller_number) : c.channel === "web" ? "Web test call" : "—"} />
          <Row k="Stage" v={c.stage ?? "—"} />
          <Row k="Ended" v={c.ended_reason ?? (c.status === "in_progress" ? "in progress" : "—")} />
          <Row k="Vapi call id" v={<span className="font-mono text-xs">{c.vapi_call_id}</span>} />
          {c.patient_id && (
            <Row
              k="Patient"
              v={
                <Link href={`/record?id=${c.patient_id}`} onClick={() => remember({ patientId: c.patient_id! })} className="text-accent-text hover:underline">
                  {c.patient_name ?? "Open record"} →
                </Link>
              }
            />
          )}
          {analysis?.sentiment && <Row k="Sentiment" v={analysis.sentiment} />}
        </dl>
        {(analysis?.summary || c.summary) && (
          <p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-700">{analysis?.summary ?? c.summary}</p>
        )}
        {c.recording_url && (
          <div className="mt-3">
            <audio controls src={c.recording_url} className="w-full" />
          </div>
        )}
      </Card>

      <AskAboutCall key={c.id} callId={c.id} llmConfigured={Boolean(status.data?.llm.configured)} model={status.data?.llm.model} />
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border py-1.5">
      <dt className="text-gray-600">{k}</dt>
      <dd className="truncate text-right font-medium">{v}</dd>
    </div>
  );
}

function CaptureChips({ capture }: { capture: CaptureEvent }) {
  const fields = Object.entries(capture.fields);
  const errors = Object.entries(capture.errors ?? {});
  if (!fields.length && !errors.length && !capture.reset) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-1 py-0.5">
      <span className="text-[11px] uppercase tracking-wide text-muted">Extracted this turn</span>
      {capture.reset && <Badge tone="amber">started over</Badge>}
      {fields.map(([k, v]) => (
        <span key={k} className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700">
          {LABEL[k] ?? k}: {String(v)}
        </span>
      ))}
      {errors.map(([k, v]) => (
        <span key={k} className="rounded-md bg-danger-soft px-2 py-0.5 text-xs text-danger-text" title={v}>
          {LABEL[k] ?? k}: invalid
        </span>
      ))}
      {capture.corrections?.length > 0 && (
        <Badge tone="amber">
          {capture.corrections.length} correction{capture.corrections.length === 1 ? "" : "s"}
        </Badge>
      )}
    </div>
  );
}

type LayoutItem =
  | { kind: "message"; role: "assistant" | "user"; content: string; highlight: boolean }
  | { kind: "capture"; capture: CaptureEvent };

/** Interleave capture events with the transcript and flag assistant turns that follow an error/correction. */
function buildLayout(c: CallDetail): { items: LayoutItem[] } {
  const messages = c.messages ?? [];
  const byTurn = new Map<number, CaptureEvent[]>();
  for (const cap of c.captures ?? []) {
    const idx = Math.min(Math.max(cap.turn_index - 1, 0), Math.max(messages.length - 1, 0));
    byTurn.set(idx, [...(byTurn.get(idx) ?? []), cap]);
  }
  const highlightNext = new Set<number>();
  for (const [idx, caps] of byTurn) {
    if (caps.some((cap) => Object.keys(cap.errors ?? {}).length || (cap.corrections?.length ?? 0) > 0 || cap.reset)) {
      for (let j = idx + 1; j < messages.length; j++) {
        if (messages[j].role === "assistant") {
          highlightNext.add(j);
          break;
        }
      }
    }
  }
  const items: LayoutItem[] = [];
  messages.forEach((m, i) => {
    items.push({ kind: "message", role: m.role, content: m.content, highlight: highlightNext.has(i) });
    for (const cap of byTurn.get(i) ?? []) items.push({ kind: "capture", capture: cap });
  });
  if (!messages.length) for (const cap of c.captures ?? []) items.push({ kind: "capture", capture: cap });
  return { items };
}
