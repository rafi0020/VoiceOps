import { expect, test } from "@playwright/test";
import { LARKSPUR, signIn } from "./helpers";

test("signing in through the form lands on the Call screen", async ({ page }) => {
  await page.goto("/login/");
  await page.getByLabel("E-mail").fill(LARKSPUR.viewer[0]);
  await page.getByLabel("Password").fill(LARKSPUR.viewer[1]);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Call", exact: true })).toBeVisible();
});

for (const [role, account, live, approvals, admin] of [
  ["viewer", LARKSPUR.viewer, false, false, false],
  ["agent", LARKSPUR.agent, true, false, false],
  ["supervisor", LARKSPUR.supervisor, true, true, false],
  ["admin", LARKSPUR.admin, true, true, true],
] as const) {
  test(`${role === "admin" || role === "agent" ? "an" : "a"} ${role} sees what that role may use`, async ({ page }) => {
    await signIn(page, account);
    await page.getByRole("button", { name: "Menu" }).click(); // the destinations live in the menu drawer
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: /calls/i })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^live/i })).toHaveCount(live ? 1 : 0);
    await expect(nav.getByRole("link", { name: /approvals/i })).toHaveCount(approvals ? 1 : 0);
    await expect(nav.getByRole("link", { name: /administration/i })).toHaveCount(admin ? 1 : 0);
  });
}
