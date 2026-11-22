import { expect, test } from "@playwright/test";

// Needs frames for 21 Nov: `uv run src/recorder.py --backfill 2026-11-21T13:50Z 2026-11-21T14:51Z`
test("a link opens a replay at its speed, which pauses, plays and goes back to live", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => message.type() === "error" && errors.push(message.text()));

  await page.goto("/?at=2026-11-21T14:20:00Z&speed=10#map=9.00/51.5000/-0.1500");

  // The status bar: the moment, the mode, and how many trains are placed
  const placed = page.getByText(/trains placed/);
  const bar = page.locator("div", { has: placed }).last();
  await expect(bar).toContainText("replay 10×", { timeout: 20_000 });
  await expect
    .poll(async () => Number(((await placed.textContent()) ?? "").replace(/,/g, "").replace(/[^\d].*$/, "")))
    .toBeGreaterThan(100);

  // At 10x the clock passes 14:20:30 within a few seconds
  const clock = page.locator("strong").first();
  await expect.poll(() => clock.textContent(), { timeout: 8_000 }).toMatch(/14:2[0-9]:[3-5]\d|14:2[1-9]/);

  const timeline = page.getByRole("group", { name: "Timeline" });
  await timeline.getByRole("button", { name: "Pause" }).click();
  await expect(bar).toContainText("paused");
  await expect(page).toHaveURL(/paused=1/);
  await expect(page).toHaveURL(/#map=9\.00\/51\.5000\/-0\.1500/);
  const paused = await clock.textContent();
  await page.waitForTimeout(1500);
  expect(await clock.textContent()).toBe(paused);

  await timeline.getByRole("button", { name: "60×" }).click();
  await timeline.getByRole("button", { name: "Play" }).click();
  await expect(bar).toContainText("replay 60×");
  await expect(page).toHaveURL(/speed=60/);

  await timeline.getByRole("button", { name: "Live" }).click();
  await expect(page).not.toHaveURL(/at=/);
  await expect(bar).not.toContainText("replay");

  expect(errors).toEqual([]);
});
