"use client";

import { useSyncExternalStore } from "react";

const TOKEN_KEY = "pva.token";
const USER_KEY = "pva.user";
const SELECTION_KEY = "pva.selection";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

// Tiny external store so React components can subscribe to localStorage-backed state
// (useSyncExternalStore) instead of copying it into component state inside effects.
const listeners = new Set<() => void>();
function emit() {
  listeners.forEach((l) => l());
}
function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export function setSession(token: string, user: unknown) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* ignore */
  }
  emit();
}

export function clearToken() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    /* ignore */
  }
  emit();
}

export function getStoredUser<T = { email: string; full_name: string | null }>(): T | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/** Remember the last opened patient/call so the Record / Transcript tabs have something to show. */
export interface Selection {
  patientId?: string;
  callId?: string;
}

const EMPTY_SELECTION: Selection = {};
let selectionCache: { raw: string | null; value: Selection } = { raw: null, value: EMPTY_SELECTION };

export function getSelection(): Selection {
  try {
    const raw = window.localStorage.getItem(SELECTION_KEY);
    if (raw === selectionCache.raw) return selectionCache.value; // stable reference for useSyncExternalStore
    const value = raw ? (JSON.parse(raw) as Selection) : EMPTY_SELECTION;
    selectionCache = { raw, value };
    return value;
  } catch {
    return EMPTY_SELECTION;
  }
}

export function remember(partial: Selection) {
  try {
    window.localStorage.setItem(SELECTION_KEY, JSON.stringify({ ...getSelection(), ...partial }));
  } catch {
    /* ignore */
  }
  emit();
}

/** true = logged in, false = not, null = not mounted yet (SSR/static export). */
export function useAuthed(): boolean | null {
  return useSyncExternalStore(subscribe, () => Boolean(getToken()), () => null);
}

/** Last opened patient/call ids (reactive). */
export function useSelection(): Selection {
  return useSyncExternalStore(subscribe, getSelection, () => EMPTY_SELECTION);
}
