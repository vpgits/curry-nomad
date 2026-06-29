import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { SignJWT } from "jose";

import { AUTH_SECRET } from "@/lib/auth-secret";

// Plane 1 — app login (identity only). The Google provider requests ONLY openid/email/profile here;
// the heavy Workspace scopes (Gmail/Calendar) are a SEPARATE, incremental grant (see
// app/api/google/*). NextAuth owns the OAuth dance, the session cookie, and CSRF.
//
// The signing secret (lib/auth-secret) doubles as the key the backend (auth.py) verifies the minted
// Aegra token with, so AUTH_SECRET here MUST equal the backend's NEXTAUTH_SECRET in production.

export const { handlers, auth } = NextAuth({
  trustHost: true,
  secret: AUTH_SECRET,
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      // `prompt: select_account` always shows Google's account chooser, so an operator can pick or
      // switch which account they sign in as (the standard multi-tenant login).
      authorization: { params: { scope: "openid email profile", prompt: "select_account" } },
    }),
  ],
  callbacks: {
    async session({ session, token }) {
      // Mint a short HS256 JWT the Aegra backend verifies (auth.py) to identify the operator and
      // scope threads to them. Exposed on the session so the client can attach it as a Bearer header
      // to Aegra calls (useStream defaultHeaders). It is identity ONLY — the Google Workspace access
      // token travels separately, per run (see components/thread + app/api/google/token).
      const key = new TextEncoder().encode(AUTH_SECRET);
      session.aegraToken = await new SignJWT({
        sub: token.sub,
        email: session.user?.email,
        name: session.user?.name,
      })
        .setProtectedHeader({ alg: "HS256" })
        .setIssuedAt()
        .setExpirationTime("1h")
        .sign(key);
      return session;
    },
  },
});
