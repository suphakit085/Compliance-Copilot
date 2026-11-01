import { Suspense } from "react";
import { AppShell } from "@/components/app-shell";

// AppShell reads the URL (usePathname) for nav and history highlighting; on dynamic routes
// such as /c/[id] that value only exists at request time, so it streams in under Suspense.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<div className="h-dvh bg-background" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
