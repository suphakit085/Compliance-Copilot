import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/lib/server";

export async function POST() {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  return Response.json({ ok: true });
}
