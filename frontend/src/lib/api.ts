/**
 * Typed client for the FastAPI backend. Every response uses the {data, error} envelope.
 * In production the dashboard is served by FastAPI itself, so relative URLs work; in `next dev`
 * set NEXT_PUBLIC_API_URL=http://localhost:8000.
 */

import { getToken, clearToken } from "./auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";
export const UI_BASE = "/app";

export interface ApiError {
  code: string;
  message: string;
  details?: { field: string | null; message: string }[];
}

export class ApiRequestError extends Error {
  status: number;
  error: ApiError;
  constructor(status: number, error: ApiError) {
    super(error.message);
    this.status = status;
    this.error = error;
  }
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const d of this.error.details ?? []) if (d.field) out[d.field] = d.message;
    return out;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers as Record<string, string>) };
  if (init.body) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  let body: { data: T; error: ApiError | null } | null = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    if (res.status === 401 && token && typeof window !== "undefined") {
      clearToken();
      if (!window.location.pathname.startsWith(`${UI_BASE}/login`)) window.location.assign(`${UI_BASE}/login`);
    }
    throw new ApiRequestError(res.status, body?.error ?? { code: "http_error", message: `HTTP ${res.status}` });
  }
  return body!.data;
}

// ---------------------------------------------------------------- types
export type Sex = "Male" | "Female" | "Other" | "Decline to Answer";

export interface Patient {
  patient_id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string; // YYYY-MM-DD
  sex: Sex;
  phone_number: string; // 10 digits
  email: string | null;
  address_line_1: string;
  address_line_2: string | null;
  city: string;
  state: string;
  zip_code: string;
  insurance_provider: string | null;
  insurance_member_id: string | null;
  preferred_language: string;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  status: "active" | "deleted";
}

export type PatientInput = Partial<Omit<Patient, "patient_id" | "created_at" | "updated_at" | "deleted_at" | "status">>;

export interface CallSummary {
  id: string;
  vapi_call_id: string;
  patient_id: string | null;
  matched_patient_id: string | null;
  caller_number: string | null;
  channel: string;
  status: "in_progress" | "ended";
  outcome: "registered" | "updated" | "partial" | "failed" | null;
  stage: string | null;
  draft: Record<string, string>;
  fields_captured: number;
  corrections: number;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  summary: string | null;
  recording_url: string | null;
  patient_name: string | null;
  insurance_provider: string | null;
}

export interface TranscriptMessage {
  role: "assistant" | "user";
  content: string;
  at?: string | null;
  seconds_from_start?: number | null;
  source?: string;
}

export interface CaptureEvent {
  at: string;
  turn_index: number;
  fields: Record<string, string>;
  errors: Record<string, string>;
  corrections: { field: string; from: string; to: string }[];
  reset: boolean;
}

export interface CallDetail extends CallSummary {
  messages: TranscriptMessage[];
  captures: CaptureEvent[];
  analysis: Record<string, unknown> | null;
  ended_reason: string | null;
}

export interface Status {
  api: string;
  version: string;
  environment: string;
  database: { connected: boolean; engine: string; error: string | null };
  webhook: { last_at: string | null; last_type: string | null };
  llm: { model: string; configured: boolean; last_turn_at: string | null; last_latency_ms: number | null };
  vapi: { configured: boolean; assistant_id: string | null; phone_number: string | null };
  active_call: { id: string; vapi_call_id: string; caller: string; stage: string | null; elapsed_seconds: number; channel: string } | null;
  server_time: string;
}

export interface Stats {
  patients_registered: number;
  calls_today: number;
  completion_rate: number | null;
  avg_call_seconds: number | null;
  calls_total: number;
  recent: CallSummary[];
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

// ---------------------------------------------------------------- endpoints
export const endpoints = {
  login: (email: string, password: string) =>
    api<TokenResponse>("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  signup: (email: string, password: string, full_name?: string) =>
    api<TokenResponse>("/api/v1/auth/signup", { method: "POST", body: JSON.stringify({ email, password, full_name }) }),
  me: () => api<User>("/api/v1/auth/me"),
  status: () => api<Status>("/api/v1/dashboard/status"),
  stats: () => api<Stats>("/api/v1/dashboard/stats"),
  patients: (includeDeleted = true) => api<Patient[]>(`/patients?include_deleted=${includeDeleted}&limit=500`),
  patient: (id: string) => api<Patient>(`/patients/${id}?include_deleted=true`),
  updatePatient: (id: string, body: PatientInput) =>
    api<Patient>(`/patients/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deletePatient: (id: string) => api<{ patient_id: string; deleted_at: string }>(`/patients/${id}`, { method: "DELETE" }),
  calls: (limit = 100) => api<CallSummary[]>(`/api/v1/calls?limit=${limit}`),
  call: (id: string) => api<CallDetail>(`/api/v1/calls/${id}`),
  patientCalls: (id: string) => api<CallSummary[]>(`/api/v1/patients/${id}/calls`),
  recordingUrl: (callId: string) => api<{ url: string }>(`/api/v1/calls/${callId}/recording-url`),
};
