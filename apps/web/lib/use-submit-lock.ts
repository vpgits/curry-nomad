"use client";

import { useCallback, useRef, useState } from "react";

// Guard an async submit handler against a double-fire during its pre-submit await window — e.g.
// `await buildSubmitConfig()`'s token fetch — BEFORE `stream.isLoading` flips true. Without this, a
// fast second click (double-Approve, or Approve then Reject) passes the `isLoading === false` check
// and fires a second run against the same interrupt — at worst executing an irreversible write twice.
// The ref is the SYNCHRONOUS gate (two clicks in the same tick can't both pass it); `locked` drives
// button disabling. It resets in a `finally`, by which point `isLoading` has taken over the disable
// for the rest of the run.
export function useSubmitLock(): readonly [
  boolean,
  (fn: () => Promise<void> | void) => Promise<void>,
] {
  const lockRef = useRef(false);
  const [locked, setLocked] = useState(false);
  const run = useCallback(async (fn: () => Promise<void> | void) => {
    if (lockRef.current) return;
    lockRef.current = true;
    setLocked(true);
    try {
      await fn();
    } finally {
      lockRef.current = false;
      setLocked(false);
    }
  }, []);
  return [locked, run] as const;
}
