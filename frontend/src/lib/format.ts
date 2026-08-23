export function formatPhone(digits: string | null | undefined): string {
  if (!digits) return "—";
  const d = digits.replace(/\D/g, "").slice(-10);
  if (d.length !== 10) return digits;
  return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`;
}

/** YYYY-MM-DD -> MM/DD/YYYY (spec format). */
export function formatDob(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[2]}/${m[3]}/${m[1]}` : iso;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function formatDurationWords(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m ? `${m}m ${s}s` : `${s}s`;
}

export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return `${day}, ${time} UTC`;
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const diff = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

/** First hex-looking group of a call id: "3a4e40c4-…" -> "3a4e", "call-4c81-demo" -> "4c81". */
export function shortId(id: string): string {
  const group = id.split("-").find((part) => /^[0-9a-f]{4,}$/i.test(part));
  return (group ?? id.replace(/-/g, "")).slice(0, 4);
}

export const FIELD_LABELS: Record<string, string> = {
  first_name: "First name",
  last_name: "Last name",
  date_of_birth: "Date of birth",
  sex: "Sex",
  phone_number: "Phone",
  email: "Email",
  address_line_1: "Street",
  address_line_2: "Unit",
  city: "City",
  state: "State",
  zip_code: "ZIP",
  insurance_provider: "Provider",
  insurance_member_id: "Member ID",
  preferred_language: "Language",
  emergency_contact_name: "Name",
  emergency_contact_phone: "Phone",
};
