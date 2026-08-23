"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { ApiRequestError, endpoints, type Patient, type PatientInput } from "@/lib/api";
import { formatDob } from "@/lib/format";
import { Button, Field, Input } from "./ui";

const SEX_OPTIONS = ["Male", "Female", "Other", "Decline to Answer"];

type FormState = Record<string, string>;

function toForm(p: Patient): FormState {
  return {
    first_name: p.first_name,
    last_name: p.last_name,
    date_of_birth: formatDob(p.date_of_birth),
    sex: p.sex,
    phone_number: p.phone_number,
    email: p.email ?? "",
    address_line_1: p.address_line_1,
    address_line_2: p.address_line_2 ?? "",
    city: p.city,
    state: p.state,
    zip_code: p.zip_code,
    insurance_provider: p.insurance_provider ?? "",
    insurance_member_id: p.insurance_member_id ?? "",
    preferred_language: p.preferred_language,
    emergency_contact_name: p.emergency_contact_name ?? "",
    emergency_contact_phone: p.emergency_contact_phone ?? "",
  };
}

export function EditPatientModal({ patient, onClose, onSaved }: { patient: Patient; onClose: () => void; onSaved: (p: Patient) => void }) {
  const initial = toForm(patient);
  const [form, setForm] = useState<FormState>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    // Partial update: send only the fields that changed (PUT accepts partial bodies).
    const changes: PatientInput = {};
    for (const [k, v] of Object.entries(form)) {
      if (v !== initial[k]) (changes as Record<string, string | null>)[k] = v === "" ? null : v;
    }
    if (!Object.keys(changes).length) {
      onClose();
      return;
    }
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      onSaved(await endpoints.updatePatient(patient.patient_id, changes));
    } catch (err) {
      if (err instanceof ApiRequestError) {
        setErrors(err.fieldErrors());
        setMessage(err.error.message);
      } else setMessage("Could not reach the API.");
    } finally {
      setSaving(false);
    }
  }

  const text = (k: string, label: string, props: Record<string, unknown> = {}) => (
    <Field label={label} error={errors[k]}>
      <Input value={form[k]} onChange={set(k)} {...props} />
    </Field>
  );

  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/30 p-4 sm:items-center" onClick={onClose}>
      <form onSubmit={save} onClick={(e) => e.stopPropagation()} className="card max-h-[92vh] w-full max-w-2xl overflow-y-auto p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-lg font-semibold">Edit patient</div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {text("first_name", "First name")}
          {text("last_name", "Last name")}
          {text("date_of_birth", "Date of birth (MM/DD/YYYY)", { placeholder: "03/14/1987" })}
          <Field label="Sex" error={errors.sex}>
            <select value={form.sex} onChange={set("sex")} className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm">
              {SEX_OPTIONS.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </Field>
          {text("phone_number", "Phone (10 digits)")}
          {text("email", "Email", { type: "email" })}
          {text("address_line_1", "Street address")}
          {text("address_line_2", "Apt / suite / unit")}
          {text("city", "City")}
          {text("state", "State (2 letters)", { maxLength: 20 })}
          {text("zip_code", "ZIP", { placeholder: "10012 or 10012-1234" })}
          {text("preferred_language", "Preferred language")}
          {text("insurance_provider", "Insurance provider")}
          {text("insurance_member_id", "Member ID")}
          {text("emergency_contact_name", "Emergency contact name")}
          {text("emergency_contact_phone", "Emergency contact phone")}
        </div>
        {message && <div className="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger-text">{message}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            Save changes
          </Button>
        </div>
      </form>
    </div>
  );
}
