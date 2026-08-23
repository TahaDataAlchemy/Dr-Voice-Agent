"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { Avatar, Badge, Card, Empty, Spinner, type Tone } from "@/components/ui";
import { endpoints, type CallSummary, type Patient } from "@/lib/api";
import { remember } from "@/lib/auth";
import { formatDob, formatPhone } from "@/lib/format";

interface Row {
  key: string;
  href: string;
  name: string;
  dob: string;
  phone: string;
  insurance: string;
  badge: { label: string; tone: Tone };
  muted: boolean;
  onOpen: () => void;
  search: string;
}

export default function PatientsPage() {
  return (
    <Shell title="Patients">
      <PatientsList />
    </Shell>
  );
}

function PatientsList() {
  const patients = useQuery({ queryKey: ["patients"], queryFn: () => endpoints.patients(true), refetchInterval: 8000 });
  const calls = useQuery({ queryKey: ["calls"], queryFn: () => endpoints.calls(100), refetchInterval: 8000 });
  const [q, setQ] = useState("");

  // Most recent call actually LINKED to each patient (registered/updated on it), so selecting a
  // patient primes *their* transcript — not a call that merely matched their phone number.
  const latestCallByPatient = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of calls.data ?? []) {
      if (c.patient_id && !map.has(c.patient_id)) map.set(c.patient_id, c.id); // calls are newest-first
    }
    return map;
  }, [calls.data]);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (const p of patients.data ?? []) out.push(patientRow(p, latestCallByPatient.get(p.patient_id)));
    // Abandoned calls with a draft but no patient record show up as "Partial" rows.
    for (const c of calls.data ?? []) {
      if (c.patient_id || c.status === "in_progress" || !c.draft || !(c.draft.first_name || c.draft.phone_number)) continue;
      out.push(partialRow(c));
    }
    return out;
  }, [patients.data, calls.data, latestCallByPatient]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return rows;
    const digits = term.replace(/\D/g, "");
    return rows.filter((r) => r.search.includes(term) || (digits && r.search.replace(/\D/g, "").includes(digits)));
  }, [rows, q]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, phone, or DOB"
            className="w-full rounded-xl border border-border bg-card px-4 py-2.5 text-sm placeholder:text-gray-400"
          />
        </div>
        <button
          onClick={() => setQ("")}
          aria-label="Clear search"
          className="rounded-xl border border-border bg-card p-2.5 text-gray-500 hover:bg-gray-50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <Card>
        {patients.isLoading ? (
          <Spinner />
        ) : filtered.length ? (
          <div className="row-divider">
            {filtered.map((r) => (
              <Link key={r.key} href={r.href} onClick={r.onOpen} className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50">
                <Avatar name={r.name} />
                <div className="min-w-0 flex-1">
                  <div className={`truncate text-sm font-semibold ${r.muted ? "text-gray-500" : ""}`}>{r.name}</div>
                  <div className="truncate text-xs text-muted">
                    {r.dob} · {r.phone} · {r.insurance}
                  </div>
                </div>
                {r.badge.tone === "gray" ? (
                  <span className="text-xs text-muted">{r.badge.label}</span>
                ) : (
                  <Badge tone={r.badge.tone}>{r.badge.label}</Badge>
                )}
              </Link>
            ))}
          </div>
        ) : (
          <Empty>{q ? "No patients match your search." : "No patients yet."}</Empty>
        )}
      </Card>
      <div className="px-1 text-xs text-muted">
        {rows.length} record{rows.length === 1 ? "" : "s"} · partial rows are calls that ended before the registration was confirmed
      </div>
    </div>
  );
}

function patientRow(p: Patient, latestCallId?: string): Row {
  const name = `${p.first_name} ${p.last_name}`;
  const deleted = p.status === "deleted";
  return {
    key: p.patient_id,
    href: `/record?id=${p.patient_id}`,
    name,
    dob: formatDob(p.date_of_birth),
    phone: formatPhone(p.phone_number),
    insurance: p.insurance_provider ?? "—",
    badge: deleted ? { label: "Deleted", tone: "gray" } : { label: "Active", tone: "green" },
    muted: deleted,
    // Remember the patient AND their latest call, so the Transcript tab opens their conversation.
    onOpen: () => remember({ patientId: p.patient_id, callId: latestCallId }),
    search: `${name} ${p.phone_number} ${formatPhone(p.phone_number)} ${p.date_of_birth} ${formatDob(p.date_of_birth)} ${p.email ?? ""} ${p.insurance_provider ?? ""}`.toLowerCase(),
  };
}

function partialRow(c: CallSummary): Row {
  const name = [c.draft.first_name, c.draft.last_name].filter(Boolean).join(" ") || c.patient_name || "Unknown caller";
  const phone = c.draft.phone_number ?? c.caller_number ?? "";
  return {
    key: `call-${c.id}`,
    href: `/transcript?id=${c.id}`,
    name,
    dob: formatDob(c.draft.date_of_birth),
    phone: formatPhone(phone),
    insurance: c.draft.insurance_provider ?? "—",
    badge: { label: "Partial", tone: "amber" },
    muted: false,
    onOpen: () => remember({ callId: c.id, patientId: undefined }),
    search: `${name} ${phone} ${formatPhone(phone)} ${c.draft.date_of_birth ?? ""} ${formatDob(c.draft.date_of_birth)}`.toLowerCase(),
  };
}
