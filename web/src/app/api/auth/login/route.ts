import { cookies } from "next/headers";
import { backendFetch, SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/server";

export async function POST(request: Request) {
  const body = await request.json();
  let res: Response;
  try {
    res = await backendFetch("/auth/login", {
      method: "POST",
      // lets the API rate-limit by the visitor's address (it trusts this header only when configured to)
      headers: {
        "Content-Type": "application/json",
        ...(request.headers.get("x-forwarded-for") ? { "X-Forwarded-For": request.headers.get("x-forwarded-for")! } : {}),
      },
      body: JSON.stringify({ username: body.username, password: body.password }),
    });
  } catch {
    return Response.json({ detail: "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ API ได้ กรุณาลองใหม่" }, { status: 502 });
  }
  if (!res.ok) {
    if (res.status === 429) {
      // lockout / rate-limit messages are written by the API (they include the wait time)
      const data = await res.json().catch(() => null);
      return Response.json(
        { detail: data?.detail ?? "ลองใหม่อีกครั้งภายหลัง" },
        { status: 429, headers: { "Retry-After": res.headers.get("retry-after") ?? "60" } },
      );
    }
    const detail = res.status === 401 ? "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง" : "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่";
    return Response.json({ detail }, { status: res.status });
  }
  const data = await res.json();
  const store = await cookies();
  // httpOnly: page scripts can never read the token, which limits the blast radius of XSS.
  store.set(SESSION_COOKIE, data.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return Response.json({ user: data.user });
}
