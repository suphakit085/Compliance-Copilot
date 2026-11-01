import { backendFetch } from "@/lib/server";

/** Whether the API has SSO configured (decides if the login page shows the SSO button). */
export async function GET() {
  try {
    const res = await backendFetch("/auth/sso/config");
    return Response.json(res.ok ? await res.json() : { enabled: false });
  } catch {
    return Response.json({ enabled: false });
  }
}
