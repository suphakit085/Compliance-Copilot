import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { backendFetch, SESSION_COOKIE } from "@/lib/server";

/**
 * Same-origin proxy to the FastAPI service. Attaches the session token from the
 * httpOnly cookie; only an allow-list of API prefixes is reachable from the browser.
 */
const ALLOWED = ["me", "chat", "conversations", "feedback", "documents", "gap-analysis", "audit", "health", "eval", "terms"];

async function forward(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  if (!ALLOWED.includes(path[0])) {
    return Response.json({ detail: "not found" }, { status: 404 });
  }
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  const search = request.nextUrl.search;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let res: Response;
  try {
    res = await backendFetch(`/${path.join("/")}${search}`, {
      method: request.method,
      token,
      headers: hasBody ? { "Content-Type": "application/json" } : undefined,
      body: hasBody ? await request.text() : undefined,
    });
  } catch {
    return Response.json({ detail: "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ API ได้" }, { status: 502 });
  }
  if (res.status === 401) {
    store.delete(SESSION_COOKIE);
  }
  const headers: Record<string, string> = { "Content-Type": res.headers.get("content-type") ?? "application/json" };
  if (res.status === 429) headers["Retry-After"] = res.headers.get("retry-after") ?? "60";
  return new Response(res.body, { status: res.status, headers });
}

export { forward as GET, forward as POST };
