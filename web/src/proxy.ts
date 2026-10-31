import { NextResponse, type NextRequest } from "next/server";

/** Send unauthenticated visitors to /login (authorisation itself is enforced by the API). */
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has("cc_session");
  const isLogin = request.nextUrl.pathname === "/login";
  if (!hasSession && !isLogin) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasSession && isLogin) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|ico)$).*)"],
};
