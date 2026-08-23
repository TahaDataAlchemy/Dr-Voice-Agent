"use client";

import { Phone } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiRequestError, endpoints } from "@/lib/api";
import { getToken, setSession } from "@/lib/auth";
import { Button, Field, Input } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/");
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setFieldErrors({});
    try {
      const res =
        mode === "login" ? await endpoints.login(email, password) : await endpoints.signup(email, password, fullName || undefined);
      setSession(res.access_token, res.user);
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiRequestError) {
        setFieldErrors(err.fieldErrors());
        setError(err.error.message);
      } else {
        setError("Could not reach the API. Is the backend running?");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
          <Phone className="h-5 w-5" />
        </div>
        <div>
          <div className="text-lg font-semibold">Patient Voice Agent</div>
          <div className="text-sm text-muted">Registration dashboard</div>
        </div>
      </div>
      <form onSubmit={submit} className="card space-y-4 p-6">
        <h1 className="text-xl font-semibold">{mode === "login" ? "Sign in" : "Create an account"}</h1>
        {mode === "signup" && (
          <Field label="Full name (optional)" error={fieldErrors.full_name}>
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Dr. Priya Patel" autoComplete="name" />
          </Field>
        )}
        <Field label="Email" error={fieldErrors.email}>
          <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@clinic.org" autoComplete="email" />
        </Field>
        <Field label="Password" error={fieldErrors.password}>
          <Input
            type="password"
            required
            minLength={mode === "signup" ? 8 : 1}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === "signup" ? "At least 8 characters" : "••••••••"}
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
          />
        </Field>
        {error && <div className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger-text">{error}</div>}
        <Button type="submit" variant="primary" loading={loading} className="w-full justify-center">
          {mode === "login" ? "Sign in" : "Sign up"}
        </Button>
        <p className="text-center text-sm text-muted">
          {mode === "login" ? (
            <>
              No account? <Link href="/signup" className="text-accent-text hover:underline">Sign up</Link>
            </>
          ) : (
            <>
              Already registered? <Link href="/login" className="text-accent-text hover:underline">Sign in</Link>
            </>
          )}
        </p>
        {mode === "login" && (
          <p className="text-center text-xs text-muted">
            Demo login: <span className="font-mono">demo@example.com</span> / <span className="font-mono">demo12345</span>
          </p>
        )}
      </form>
    </main>
  );
}
