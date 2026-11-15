import { expect, test } from "@playwright/test";
import { LARKSPUR, signIn } from "./helpers";

// Chromium's fake microphone, so the call screen can open the microphone in a headless browser.
test.use({ launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] } });

test("press to talk sends the microphone only while the button or Space is held, and letting go ends the turn", async ({ page }) => {
  let audioFrames = 0;
  let endTurns = 0;
  page.on("websocket", (socket) => {
    socket.on("framesent", ({ payload }) => {
      if (typeof payload === "string") {
        if (payload.includes('"end_turn"')) endTurns += 1;
      } else {
        audioFrames += 1;
      }
    });
  });
  await signIn(page, LARKSPUR.agent);
  await page.getByRole("button", { name: "call by voice" }).click();
  await expect(page.getByRole("button", { name: "press to talk" })).toBeVisible();
  await page.getByRole("button", { name: "press to talk" }).click();
  await expect(page.getByRole("button", { name: "hold to talk" })).toBeVisible();

  await page.waitForTimeout(300); // frames already on their way when the mode changed
  const idle = audioFrames;
  await page.waitForTimeout(1500);
  expect(audioFrames - idle).toBeLessThan(3); // not held: the microphone is not sent

  const box = await page.getByRole("button", { name: "hold to talk" }).boundingBox();
  if (!box) throw new Error("the hold to talk button has no position");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  const held = audioFrames;
  await page.waitForTimeout(1200);
  expect(audioFrames - held).toBeGreaterThan(5); // held: the microphone is sent
  await page.mouse.up();
  await expect.poll(() => endTurns).toBeGreaterThan(0); // letting go ends the turn on the server

  const afterRelease = audioFrames;
  await page.waitForTimeout(800);
  expect(audioFrames - afterRelease).toBeLessThan(3);

  await page.keyboard.down("Space");
  await page.waitForTimeout(600);
  const spaceHeld = audioFrames;
  await page.keyboard.up("Space");
  expect(spaceHeld).toBeGreaterThan(afterRelease);
  await expect.poll(() => endTurns).toBeGreaterThan(1);
  await expect(page.getByRole("button", { name: "open mic" })).toBeVisible(); // Space did not switch the mode back
});
