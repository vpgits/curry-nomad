import "next-auth";

declare module "next-auth" {
  interface Session {
    // The HS256 JWT the backend (auth.py) verifies; minted in the session callback. See auth.ts.
    aegraToken?: string;
  }
}
