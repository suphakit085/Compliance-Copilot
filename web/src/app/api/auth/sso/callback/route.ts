import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { backendFetch, SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/server";

/** The identity provider redirects here with ?code&state; the API verifies everything. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const fail = (msg: string) => NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(msg)}`, url));
  const store = await cookies();
  const stateToken = store.get("cc_sso")?.value;
  store.delete({ name: "cc_sso", path: "/api/auth/sso" });

  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (url.searchParams.get("error")) return fail("การเข้าสู่ระบบด้วย SSO ถูกยกเลิก");
  if (!code || !state || !stateToken) return fail("การเข้าสู่ระบบไม่ถูกต้อง กรุณาลองใหม่");

  let res: Response;
  try {
    res = await backendFetch("/auth/sso/callback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, state, state_token: stateToken }),
    });
  } catch {
    return fail("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ API ได้");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    return fail(res.status === 401 && data?.detail ? data.detail : "เข้าสู่ระบบด้วย SSO ไม่สำเร็จ");
  }
  const data = await res.json();
  store.set(SESSION_COOKIE, data.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return NextResponse.redirect(new URL("/", url));
}
