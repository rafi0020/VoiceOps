import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// The stack runs with LLM_PROVIDER=stub by default: a rule-based stand-in model (backend/app/agent/stub.py), so these
// journeys exercise the whole system (API, socket, graph, checkpoints, speech synthesis, UI) without a provider.
export const LARKSPUR = {
  admin: ["admin@larkspur.demo", "Admin#Demo2026"],
  supervisor: ["supervisor@larkspur.demo", "Supervisor#Demo2026"],
  agent: ["agent@larkspur.demo", "Agent#Demo2026"],
  viewer: ["viewer@larkspur.demo", "Viewer#Demo2026"],
} as const;
export const FERNHILL_AGENT = ["agent@fernhill.demo", "Agent#Demo2026"] as const;
export const ACCOUNTS = [LARKSPUR.admin, LARKSPUR.supervisor, LARKSPUR.agent, LARKSPUR.viewer, FERNHILL_AGENT];
export const AUTH_DIR = "e2e/.auth";
export const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3400";
export const AMELIA = "My account is LT100001, postcode NG4 2AB, born 14 March 1985";
export const TOM = "Account LT100002, postcode LS6 3HJ, born 2 November 1979";

export async function signIn(page: Page, [email]: readonly [string, string]) {
  const state = JSON.parse(readFileSync(`${AUTH_DIR}/${email}.json`, "utf8"));
  await page.context().addCookies(state.cookies);
  await page.goto("/call/");
  await expect(page.getByRole("heading", { name: "Call", exact: true })).toBeVisible();
}

/** Start a call by text on the Call screen and say each line, waiting for the assistant's answer to each. */
export async function textCall(page: Page, lines: string[]) {
  await page.getByRole("button", { name: "call by text" }).click();
  await expect(page.getByText(/through to Larkspur Telecom/)).toBeVisible();
  for (const line of lines) {
    const before = await page.locator('.bubble[data-speaker="agent"]').count();
    await page.getByLabel("Type a message").fill(line);
    await page.getByRole("button", { name: "Send" }).click();
    await expect.poll(() => page.locator('.bubble[data-speaker="agent"]').count(), { timeout: 20_000 }).toBeGreaterThan(before);
  }
}
