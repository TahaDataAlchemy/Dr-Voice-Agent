"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Avatar, Badge, Card, Empty, Spinner, StatTile, outcomeBadge } from "@/components/ui";
import { endpoints, type CallSummary } from "@/lib/api";
import { remember } from "@/lib/auth";
import { formatDuration, formatElapsed, formatPhone } from "@/lib/format";

export default function OverviewPage() {
  return (
    <Shell title="Overview">
      <Overview />
    </Shell>
  );
}

function Overview() {
  const status = useQuery({ queryKey: ["status"], queryFn: endpoints.status, refetchInterval: 4000 });
  const stats = useQuery({ queryKey: ["stats"], queryFn: endpoints.stats, refetchInterval: 5000 });
  const [now, setNow] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const s = status.data;
  const active = s?.active_call ?? null;
  // Smooth the elapsed counter between polls.
  const elapsed = active ? active.elapsed_seconds + Math.max(0, Math.round((now - new Date(s!.server_time).getTime()) / 1000)) : 0;

  return (
    <div className="space-y-5">
      {active && (
        <div className="flex items-center justify-between gap-3 rounded-card bg-success-soft px-4 py-3" style={{ borderRadius: 14 }}>
          <div className="flex items-center gap-3">
            <span className="live-dot" />
            <div>
              <div className="text-sm font-semibold text-gray-900">
                Call in progress — {active.caller}
              </div>
              <div className="text-xs text-success-text">
                {active.stage ?? "Connecting"} · {formatElapsed(elapsed)} elapsed
              </div>
            </div>
          </div>
          <Badge tone="green">Live</Badge>
        </div>
      )}

      <div className="grid grid-cols-2 gap-6 px-1 sm:grid-cols-4">
        <StatTile label="Patients registered" value={stats.data?.patients_registered ?? "—"} />
        <StatTile label="Calls today" value={stats.data?.calls_today ?? "—"} />
        <StatTile label="Completion rate" value={stats.data ? (stats.data.completion_rate == null ? "—" : `${stats.data.completion_rate}%`) : "—"} />
        <StatTile label="Avg call length" value={stats.data ? formatDuration(stats.data.avg_call_seconds) : "—"} />
      </div>

      <Card>
        <div className="px-5 pt-5 text-base font-semibold">Recent registrations</div>
        {stats.isLoading ? (
          <Spinner />
        ) : stats.data && stats.data.recent.length ? (
          <div className="row-divider mt-2">
            {stats.data.recent.map((c) => (
              <RecentRow key={c.id} call={c} />
            ))}
          </div>
        ) : (
          <Empty>No calls yet. Dial the agent&apos;s number and the call will appear here live.</Empty>
        )}
      </Card>

      {s?.vapi.phone_number && (
        <div className="px-1 text-xs text-muted">
          Agent number: <span className="font-mono text-gray-700">{s.vapi.phone_number}</span> · model {s.llm.model}
          {s.llm.last_latency_ms != null && ` · last turn ${s.llm.last_latency_ms} ms`}
        </div>
      )}
    </div>
  );
}

function RecentRow({ call }: { call: CallSummary }) {
  const badge = outcomeBadge(call.outcome, call.status);
  const name = call.patient_name ?? "Unknown caller";
  const note =
    call.status === "in_progress"
      ? "pending"
      : call.outcome === "updated"
        ? "updated existing"
        : call.outcome === "partial"
          ? "caller hung up"
          : call.outcome === "failed"
            ? "save failed"
            : call.insurance_provider ?? "no insurance on file";
  const href = call.patient_id ? `/record?id=${call.patient_id}` : `/transcript?id=${call.id}`;
  return (
    <Link
      href={href}
      onClick={() => remember(call.patient_id ? { patientId: call.patient_id, callId: call.id } : { callId: call.id, patientId: undefined })}
      className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50"
    >
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{name}</div>
        <div className="truncate text-xs text-muted">
          {formatPhone(call.caller_number ?? call.draft.phone_number)} · {note}
        </div>
      </div>
      <Badge tone={badge.tone}>{badge.label}</Badge>
    </Link>
  );
}
