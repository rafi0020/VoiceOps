import { request } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { ACCOUNTS, AUTH_DIR, BASE } from "./helpers";

// Sign in once per account and keep the cookies. The API limits sign-ins to five a minute per e-mail address,
// so the journeys reuse these sessions instead of signing in again in every test.
export default async function globalSetup() {
  mkdirSync(AUTH_DIR, { recursive: true });
  for (const [email, password] of ACCOUNTS) {
    const api = await request.newContext({ baseURL: BASE });
    const response = await api.post("/api/auth/login", { data: { email, password } });
    if (!response.ok()) throw new Error(`could not sign in ${email}: ${response.status()} ${await response.text()}`);
    writeFileSync(`${AUTH_DIR}/${email}.json`, JSON.stringify(await api.storageState()));
    await api.dispose();
  }
}
