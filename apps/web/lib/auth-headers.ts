import { getSession } from "next-auth/react";

// The Authorization header for Aegra calls (thread search/tag), pulled from the NextAuth session's
// minted Aegra token. Empty when not signed in / auth not configured, so the keyless `noop` default
// keeps working unchanged.
export async function aegraAuthHeaders(): Promise<Record<string, string>> {
  try {
    const session = await getSession();
    return session?.aegraToken ? { Authorization: `Bearer ${session.aegraToken}` } : {};
  } catch {
    return {};
  }
}
