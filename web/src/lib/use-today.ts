"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};
const today = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD in local time

/** Today's date on the client; empty during prerender so the page stays static. */
export function useToday(): string {
  return useSyncExternalStore(subscribe, today, () => "");
}
