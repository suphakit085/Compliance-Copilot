import "server-only";

/** Backend-for-frontend helpers. The FastAPI URL and the session token never reach the browser. */

export const API_URL = process.env.COPILOT_API_URL ?? "http://localhost:8000";
export const SESSION_COOKIE = "cc_session";
export const SESSION_MAX_AGE = 8 * 60 * 60; // matches the API's JWT lifetime

export async function backendFetch(path: string, init: RequestInit & { token?: string } = {}) {
  const { token, headers, ...rest } = init;
  return fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      ...(headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: "no-store",
  });
}
