import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { SignJWT } from "jose";

// Plane 1 — app login (identity only). The Google provider requests ONLY openid/email/profile here;
// the heavy Workspace scopes (Gmail/Calendar) are a SEPARATE, incremental grant (see
// app/api/google/*). NextAuth owns the OAuth dance, the session cookie, and CSRF.
//
// The signing secret doubles as the key the backend (auth.py) verifies the minted Aegra token with,
// so AUTH_SECRET here MUST equal the backend's NEXTAUTH_SECRET. A dev fallback keeps the default
// (auth-off) stack from crashing — it's harmless because AUTH_TYPE=noop means the backend never
// verifies the token; the workspace demo sets a real, matching secret.
const AUTH_SECRET =
  process.env.AUTH_SECRET ??
  process.env.NEXTAUTH_SECRET ??
  "nora-dev-insecure-secret-please-override-0123456789";

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  secret: AUTH_SECRET,
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      authorization: { params: { scope: "openid email profile" } },
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
