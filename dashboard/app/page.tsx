"use client";

import { ReviewProvider } from "@/lib/review-context";
import { AppShell } from "@/components/review/app-shell";

// The lunaris shell hosts five lenses (Overview · Workflow · Inbox · Grid · Calendar) over ONE data
// model; the gate engine stays the single source of truth. AppShell routes the active lens itself.
export default function Page() {
  return (
    <ReviewProvider>
      <AppShell />
    </ReviewProvider>
  );
}
