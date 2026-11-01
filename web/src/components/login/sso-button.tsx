"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";

/** "Sign in with SSO" - rendered only when the API has an identity provider configured.
 *  Also shows the reason when the identity provider sends the user back with ?error=. */
export function SsoButton() {
  const params = useSearchParams();
  const error = params.get("error");
  const [sso, setSso] = useState<{ enabled: boolean; label: string } | null>(null);

  useEffect(() => {
    fetch("/api/auth/sso/config")
      .then((r) => r.json())
      .then(setSso)
      .catch(() => setSso({ enabled: false, label: "" }));
  }, []);

  return (
    <>
      {error && <p className="pop-in mt-4 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {sso?.enabled && (
        <div className="mt-4">
          <div className="mb-4 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            หรือ
            <span className="h-px flex-1 bg-border" />
          </div>
          {/* a plain link: the browser must leave for the identity provider */}
          <a
            href="/api/auth/sso/start"
            className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] border bg-background/60 text-sm font-medium transition hover:bg-white/5"
          >
            <KeyRound className="size-4 text-brand" />
            เข้าสู่ระบบด้วย {sso.label}
          </a>
        </div>
      )}
    </>
  );
}
