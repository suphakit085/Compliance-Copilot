import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server";

export const SSO_COOKIE = "cc_sso";

/** Begin sign-in: keep the signed state (CSRF + nonce + PKCE verifier) in an httpOnly cookie and
 *  send the browser to the identity provider. */
export async function GET(request: Request) {
  const fail = (msg: string) =>
    NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(msg)}`, request.url));
  let res: Response;
  try {
    res = await backendFetch("/auth/sso/start");
  } catch {
    return fail("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ API ได้");
  }
  if (!res.ok) return fail("ไม่สามารถเริ่มการเข้าสู่ระบบด้วย SSO ได้");
  const { url, state_token } = await res.json();
  const store = await cookies();
  store.set(SSO_COOKIE, state_token, {
    httpOnly: true,
    sameSite: "lax", // must survive the top-level redirect back from the identity provider
    secure: process.env.NODE_ENV === "production",
    path: "/api/auth/sso",
    maxAge: 600,
  });
  return NextResponse.redirect(url);
}
