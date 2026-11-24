// What to record for the VoiceOps demo. Run with the stack up and a model connected (see README, "Adding an AI model").
// Calls are recorded as typed calls: the text frames of the socket are kept, the audio is not.
const user = (role) => `${role}@larkspur.demo`;
const PASSWORDS = { agent: "Agent#Demo2026", supervisor: "Supervisor#Demo2026", viewer: "Viewer#Demo2026", admin: "Admin#Demo2026" };
const AMELIA = "My account is LT100001, postcode NG4 2AB, born 14 March 1985";
const TOM = "Account LT100002, postcode LS6 3HJ, born 2 November 1979";

async function step(name, fn) {
  try { await fn(); } catch (e) { console.log(`  step "${name}" skipped: ${String(e.message).split("\n")[0]}`); }
}

async function textCall(page, h, lines, { hangUp = true } = {}) {
  await page.goto("/call/");
  await h.settle(800);
  await page.getByRole("button", { name: /call by text/i }).click();
  await page.getByText(/through to Larkspur Telecom/).waitFor({ timeout: 20_000 });
  for (const line of lines) {
    const before = await page.locator('.bubble[data-speaker="agent"]').count();
    await page.getByLabel("Type a message").fill(line);
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForFunction((n) => document.querySelectorAll('.bubble[data-speaker="agent"]').length > n, before, { timeout: 90_000 });
    await h.settle(1500);
  }
  if (hangUp) {
    await page.getByRole("button", { name: /hang up/i }).click();
    await page.getByText(/the note for the crm/i).waitFor({ timeout: 60_000 }).catch(() => {});
    await h.settle(2000);
  }
}

export default {
  project: "voiceops",
  baseUrl: process.env.DEMO_BASE_URL ?? "http://localhost:3400",
  loginPath: "/login/",
  loginApi: "/api/auth/login",
  logoutApi: "/api/auth/logout",
  crawlStart: "/call/",
  crawlSeeds: ["/calls/", "/live/", "/approvals/", "/customers/", "/knowledge/", "/evaluation/", "/admin/"],
  crawlMax: 40,
  poke: true,
  pokeRows: 3,
  users: [
    { email: user("agent"), password: PASSWORDS.agent, label: "Agent" },
    { email: user("supervisor"), password: PASSWORDS.supervisor, label: "Supervisor" },
    { email: user("viewer"), password: PASSWORDS.viewer, label: "Viewer" },
    { email: user("admin"), password: PASSWORDS.admin, label: "Administrator" },
  ],
  journeys: {
    [user("agent")]: async (page, h) => {
      await step("outage call", () => textCall(page, h, ["What's my latest bill?", AMELIA, "My broadband is down"]));
      await step("credit call", () => textCall(page, h, [TOM, "Please give me a credit of 12.00 for the double charge"]));
      await step("hand-off call", () => textCall(page, h, ["I want to talk to a person please"]));
    },
  },
  after: {
    [user("supervisor")]: async (page, h) => {
      await step("approve the credit", async () => {
        await page.goto("/approvals/");
        await h.settle(1000);
        const row = page.getByRole("article", { name: /Tom Okafor/ }).filter({ hasText: "12.00" }).last();
        await h.mute(async () => {
          await row.getByRole("button", { name: /approve/i }).click({ timeout: 8000 });
          await h.settle(2500);
        });
      });
    },
  },
};
