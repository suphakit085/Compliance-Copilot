import { cookies } from "next/headers";
import { backendFetch, SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/server";

export async function POST(request: Request) {
  const body = await request.json();
  let res: Response;
  try {
    res = await backendFetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: body.username, password: body.password }),
    });
  } catch {
    return Response.json({ detail: "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ API ได้ กรุณาลองใหม่" }, { status: 502 });
  }
  if (!res.ok) {
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
