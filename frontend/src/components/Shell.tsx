"use client";

import clsx from "clsx";
import { BookOpen, FileText, LayoutGrid, LogOut, MessageSquareText, MoreHorizontal, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { clearToken, getStoredUser, useAuthed, useSelection } from "@/lib/auth";
import { Spinner } from "./ui";

const TABS = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/patients", label: "Patients", icon: Users },
  { href: "/record", label: "Record", icon: FileText },
  { href: "/transcript", label: "Transcript", icon: MessageSquareText },
] as const;

/** Page chrome: pill tabs + "…" menu + auth guard (redirects to /login when there is no token). */
export function Shell({ children, title }: { children: React.ReactNode; title?: string }) {
  const authed = useAuthed();
  const router = useRouter();
  const pathname = usePathname();
  const selection = useSelection();

  useEffect(() => {
    if (authed === false) router.replace("/login");
  }, [authed, router]);

  if (authed !== true) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-10">
        <Spinner label={authed === null ? "Loading…" : "Redirecting to login…"} />
      </main>
    );
  }

  const hrefFor = (base: string) => {
    if (base === "/record" && selection.patientId) return `/record?id=${selection.patientId}`;
    if (base === "/transcript" && selection.callId) return `/transcript?id=${selection.callId}`;
    return base;
  };

  return (
    <main className="mx-auto w-full max-w-3xl px-4 pb-16 pt-6">
      <div className="mb-5 flex items-center justify-between gap-3">
        <nav className="flex flex-wrap items-center gap-2" aria-label="Sections">
          {TABS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={hrefFor(href)}
                className={clsx(
                  "pill inline-flex items-center gap-2 px-3.5 py-2 text-sm font-medium transition hover:bg-gray-50",
                  active ? "border-gray-900 text-foreground" : "text-gray-700",
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <Menu />
      </div>
      {title && <h1 className="sr-only">{title}</h1>}
      {children}
    </main>
  );
}

function Menu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const user = typeof window !== "undefined" ? getStoredUser() : null;

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"
        aria-label="More"
      >
        <MoreHorizontal className="h-5 w-5" />
      </button>
      {open && (
        <div className="card absolute right-0 z-20 mt-1 w-56 overflow-hidden py-1 text-sm shadow-lg">
          {user && <div className="truncate px-3 py-2 text-xs text-muted">{user.email}</div>}
          <a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer" className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50">
            <BookOpen className="h-4 w-4" /> API docs
          </a>
          <button
            onClick={() => {
              clearToken();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-gray-50"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
