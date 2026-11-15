import { expect, test } from "@playwright/test";
import { AMELIA, FERNHILL_AGENT, LARKSPUR, signIn, textCall, TOM } from "./helpers";

test("a typed call checks who the caller is, finds the outage and ends with a note", async ({ page }) => {
  await signIn(page, LARKSPUR.agent);
  await textCall(page, ["What's my latest bill?", AMELIA, "My broadband is down"]);
  await expect(page.locator('.bubble[data-speaker="agent"]').nth(1)).toContainText(/account number/i); // asked to verify first
  await expect(page.getByText(/you're verified/)).toBeVisible();
  await expect(page.getByText(/known problem in your area/)).toBeVisible();
  await expect(page.getByText(/end of speech to first sound/i)).toBeVisible(); // latency is reported per turn
  await page.getByRole("button", { name: "hang up" }).click();
  await expect(page.getByText("the note for the crm")).toBeVisible({ timeout: 20_000 });
});

test("a credit over the limit waits for a supervisor, who approves it while the caller is on the line", async ({ browser }) => {
  const caller = await (await browser.newContext()).newPage();
  await signIn(caller, LARKSPUR.agent);
  await textCall(caller, [TOM, "Please give me a credit of 12.00 for the double charge"]);
  await expect(caller.getByText(/supervisor needs to approve/)).toBeVisible();

  const supervisor = await (await browser.newContext()).newPage();
  await signIn(supervisor, LARKSPUR.supervisor);
  await supervisor.goto("/approvals/");
  // The queue is oldest first; this call's credit is the newest (earlier runs may have left others pending).
  const row = supervisor.getByRole("article", { name: /Tom Okafor/ }).filter({ hasText: "12.00" }).last(); // a credit card
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "approve" }).click();
  await expect(supervisor.getByText(/Credit applied/)).toBeVisible();
  await expect(caller.getByText(/My supervisor approved the credit of 12.00/)).toBeVisible({ timeout: 20_000 });
});

test("a caller asks for a person; an agent takes the call over and replies", async ({ browser }) => {
  const caller = await (await browser.newContext()).newPage();
  await signIn(caller, LARKSPUR.viewer);
  await textCall(caller, ["I want to talk to a person please"]);
  await expect(caller.getByText(/passing you to a colleague/)).toBeVisible();

  const agent = await (await browser.newContext()).newPage();
  await signIn(agent, LARKSPUR.agent);
  await agent.goto("/live/");
  await agent.getByRole("button", { name: "open call" }).first().click(); // the call opens in a drawer
  await agent.getByRole("button", { name: "take over" }).click();
  await expect(agent.getByText(/You have the call/)).toBeVisible();
  await agent.getByLabel("Your reply").fill("Hello, this is Sam from Larkspur. How can I help?");
  await agent.getByRole("button", { name: "say" }).click();
  await expect(caller.getByText("Hello, this is Sam from Larkspur. How can I help?")).toBeVisible({ timeout: 20_000 });
});

test("another organisation cannot open a call, by URL or through the API", async ({ browser }) => {
  const larkspur = await (await browser.newContext()).newPage();
  await signIn(larkspur, LARKSPUR.agent);
  const { calls } = await (await larkspur.request.get("/api/calls?limit=1")).json();
  const id = calls[0].id as string;

  const fernhill = await (await browser.newContext()).newPage();
  await signIn(fernhill, FERNHILL_AGENT);
  expect((await fernhill.request.get(`/api/calls/${id}`)).status()).toBe(404);
  await fernhill.goto(`/calls/?id=${id}`);
  await expect(fernhill.getByText(/not found/i)).toBeVisible();
});
