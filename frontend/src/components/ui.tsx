"use client";

import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { initials } from "@/lib/format";

export type Tone = "green" | "blue" | "amber" | "red" | "gray";

const TONES: Record<Tone, string> = {
  green: "bg-success-soft text-success-text",
  blue: "bg-accent-soft text-accent-text",
  amber: "bg-warn-soft text-warn-text",
  red: "bg-danger-soft text-danger-text",
  gray: "bg-gray-100 text-gray-600",
};

export function Badge({ tone = "gray", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Avatar({ name, size = "md" }: { name: string | null | undefined; size?: "md" | "lg" }) {
  return (
    <div
      className={clsx(
        "flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold text-accent-text",
        size === "lg" ? "h-12 w-12 text-base" : "h-9 w-9 text-xs",
      )}
    >
      {initials(name)}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("card", className)}>{children}</div>;
}

export function StatTile({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="text-sm text-muted">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}

export function Button({
  variant = "secondary",
  loading,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger"; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={clsx(
        "inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "border-accent bg-accent text-white hover:bg-blue-700",
        variant === "secondary" && "border-border bg-card text-foreground hover:bg-gray-50",
        variant === "danger" && "border-red-200 bg-card text-red-600 hover:bg-red-50",
        className,
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...rest}
      className={clsx("w-full rounded-lg border border-border bg-card px-3 py-2 text-sm placeholder:text-gray-400", className)}
    />
  );
}

export function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      {children}
      {error && <span className="mt-1 block text-xs text-danger-text">{error}</span>}
    </label>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-muted">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-8 text-center text-sm text-muted">{children}</div>;
}

export function outcomeBadge(outcome: string | null, status: string): { label: string; tone: Tone } {
  if (status === "in_progress") return { label: "In call", tone: "amber" };
  switch (outcome) {
    case "registered":
      return { label: "Saved", tone: "green" };
    case "updated":
      return { label: "Matched", tone: "blue" };
    case "partial":
      return { label: "Partial", tone: "red" };
    case "failed":
      return { label: "Failed", tone: "red" };
    default:
      return { label: "Ended", tone: "gray" };
  }
}
