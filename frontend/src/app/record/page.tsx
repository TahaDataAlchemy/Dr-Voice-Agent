"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { EditPatientModal } from "@/components/EditPatientModal";
import { RecordingPlayer } from "@/components/RecordingPlayer";
import { Shell } from "@/components/Shell";
import { Avatar, Badge, Button, Card, Empty, Spinner } from "@/components/ui";
import { endpoints, type Patient } from "@/lib/api";
import { remember, useSelection } from "@/lib/auth";
import { formatDob, formatPhone, formatUtc } from "@/lib/format";

export default function RecordPage() {
  return (
    <Shell title="Patient record">
      <Suspense fallback={<Spinner />}>
        <Record />
      </Suspense>
    </Shell>
  );
}

function Record() {
  const params = useSearchParams();
  const selection = useSelection();
  const fromUrl = params.get("id");
  const id = fromUrl ?? selection.patientId ?? null;
  useEffect(() => {
    if (fromUrl) remember({ patientId: fromUrl }); // external system (localStorage) sync
  }, [fromUrl]);

  if (id) return <RecordView id={id} />;
  // No saved patient selected — if a call is selected, show its (unsaved) partial data instead of an empty state.
  if (selection.callId) return <PartialRecordView callId={selection.callId} />;
  return (
    <Card>
      <Empty>
        Pick a patient from the <Link href="/patients" className="text-accent-text hover:underline">Patients</Link> list to see their record.
      </Empty>
    </Card>
  );
}

/** A caller whose registration never completed has no saved record — show what was captured, read-only. */
function PartialRecordView({ callId }: { callId: string }) {
  const call = useQuery({ queryKey: ["call", callId], queryFn: () => endpoints.call(callId) });
  if (call.isLoading) return <Spinner />;
  const c = call.data;
  if (!c)
    return (
      <Card>
        <Empty>Nothing selected yet.</Empty>
      </Card>
    );
  // If this call actually saved/updated a patient, send them to the real record.
  if (c.patient_id) return <RecordView id={c.patient_id} />;

  const d = c.draft ?? {};
  const name = [d.first_name, d.last_name].filter(Boolean).join(" ") || c.patient_name || "Unknown caller";
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar name={name} size="lg" />
          <div>
            <div className="text-lg font-semibold">{name}</div>
            <div className="text-xs text-muted">Registration not completed — nothing was saved to the database</div>
          </div>
        </div>
        <Badge tone="amber">Partial</Badge>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-x-10 gap-y-6 sm:grid-cols-2">
        <Section title="Captured so far" rows={[
          ["First name", d.first_name ?? "—"],
          ["Last name", d.last_name ?? "—"],
          ["Date of birth", d.date_of_birth ? formatDob(d.date_of_birth) : "—"],
          ["Sex", d.sex ?? "—"],
          ["Phone", d.phone_number ? formatPhone(d.phone_number) : "—"],
        ]} />
        <Section title="Address" rows={[
          ["Street", d.address_line_1 ?? "—"],
          ["City", d.city ?? "—"],
          ["State", d.state ?? "—"],
          ["ZIP", d.zip_code ?? "—"],
        ]} />
      </div>

      <div className="mt-6">
        <Link
          href={`/transcript?id=${c.id}`}
          onClick={() => remember({ callId: c.id })}
          className="text-sm text-accent-text hover:underline"
        >
          View the call transcript →
        </Link>
      </div>
    </Card>
  );
}

function RecordView({ id }: { id: string }) {
  const qc = useQueryClient();
  const patient = useQuery({ queryKey: ["patient", id], queryFn: () => endpoints.patient(id) });
  const calls = useQuery({ queryKey: ["patient-calls", id], queryFn: () => endpoints.patientCalls(id) });
  const [editing, setEditing] = useState(false);
  const remove = useMutation({
    mutationFn: () => endpoints.deletePatient(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["patient", id] });
      qc.invalidateQueries({ queryKey: ["patients"] });
    },
  });

  if (patient.isLoading) return <Spinner />;
  if (patient.isError || !patient.data)
    return (
      <Card>
        <Empty>Patient not found.</Empty>
      </Card>
    );
  const p = patient.data;
  const deleted = p.status === "deleted";
  const callWithRecording = calls.data?.find((c) => c.recording_url) ?? null;
  const latestCall = calls.data?.[0];

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar name={`${p.first_name} ${p.last_name}`} size="lg" />
          <div>
            <div className="text-lg font-semibold">
              {p.first_name} {p.last_name}
            </div>
            <div className="font-mono text-xs text-muted">{p.patient_id}</div>
          </div>
        </div>
        <Badge tone={deleted ? "gray" : "green"}>{deleted ? "Deleted" : "Active"}</Badge>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-x-10 gap-y-6 sm:grid-cols-2">
        <Section title="Demographics" rows={[
          ["Date of birth", formatDob(p.date_of_birth)],
          ["Sex", p.sex],
          ["Phone", formatPhone(p.phone_number)],
          ["Email", p.email ?? "—"],
          ["Language", p.preferred_language],
        ]} />
        <Section title="Address" rows={[
          ["Street", p.address_line_1],
          ["Unit", p.address_line_2 ?? "—"],
          ["City", p.city],
          ["State", p.state],
          ["ZIP", p.zip_code],
        ]} />
        <Section title="Insurance" rows={[
          ["Provider", p.insurance_provider ?? "—"],
          ["Member ID", p.insurance_member_id ?? "—"],
        ]} />
        <Section title="Emergency contact" rows={[
          ["Name", p.emergency_contact_name ?? "—"],
          ["Phone", p.emergency_contact_phone ? formatPhone(p.emergency_contact_phone) : "—"],
        ]} />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        <Button onClick={() => setEditing(true)} disabled={deleted}>
          <Pencil className="h-4 w-4" /> Edit
        </Button>
        <Button
          variant="danger"
          loading={remove.isPending}
          disabled={deleted}
          onClick={() => {
            if (window.confirm(`Soft-delete ${p.first_name} ${p.last_name}? The record is kept with a deleted_at timestamp.`)) remove.mutate();
          }}
        >
          <Trash2 className="h-4 w-4" /> Soft delete
        </Button>
        {latestCall && (
          <Link
            href={`/transcript?id=${latestCall.id}`}
            onClick={() => remember({ callId: latestCall.id })}
            className="ml-auto text-sm text-accent-text hover:underline"
          >
            View transcript →
          </Link>
        )}
      </div>

      {callWithRecording && <RecordingPlayer callId={callWithRecording.id} hasRecording />}

      <div className="mt-5 text-xs text-muted">
        Created {formatUtc(p.created_at)} · updated {formatUtc(p.updated_at)}
        {p.deleted_at && ` · deleted ${formatUtc(p.deleted_at)}`}
      </div>

      {editing && (
        <EditPatientModal
          patient={p}
          onClose={() => setEditing(false)}
          onSaved={(updated: Patient) => {
            qc.setQueryData(["patient", id], updated);
            qc.invalidateQueries({ queryKey: ["patients"] });
            setEditing(false);
          }}
        />
      )}
    </Card>
  );
}

function Section({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div>
      <div className="mb-1 text-xs text-muted">{title}</div>
      <dl className="row-divider">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-4 py-2 text-sm">
            <dt className="text-gray-600">{k}</dt>
            <dd className="truncate text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
