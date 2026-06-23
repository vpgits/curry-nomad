import { handlers } from "@/auth";

// NextAuth's catch-all route (login, callback, session, signout) for the Google provider in auth.ts.
export const { GET, POST } = handlers;
