import { expect, test } from "@playwright/test";

type Position = { rid: string; headcode: string | null };

test("the map fills with trains, the clock runs, and search opens a train's details", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => message.type() === "error" && errors.push(message.text()));

  await page.goto("/");

  // Trains are placed: the status bar's count goes above zero
  const placed = page.getByText(/trains placed/);
  await expect(placed).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(async () => Number(((await placed.textContent()) ?? "").replace(/,/g, "").replace(/[^\d].*$/, "")))
    .toBeGreaterThan(100);

  // The replay clock moves on
  const clock = page.locator("strong").first();
  const first = await clock.textContent();
  await expect.poll(() => clock.textContent(), { timeout: 5_000 }).not.toBe(first);

  // Pick a headcode only one running train has, find it with search, and open it
  const { trains } = (await (await request.get("/api/positions")).json()) as { trains: Position[] };
  const counts = new Map<string, number>();
  for (const train of trains)
    if (train.headcode) counts.set(train.headcode, (counts.get(train.headcode) ?? 0) + 1);
  const train = trains.find((t) => t.headcode && counts.get(t.headcode) === 1);
  expect(train).toBeDefined();
  const headcode = train?.headcode as string;

  await page.keyboard.press("/");
  await page.getByRole("combobox").fill(headcode);
  await page.getByRole("option").filter({ hasText: headcode }).first().click();

  const panel = page.getByRole("complementary", { name: "Train details" });
  await expect(panel.getByRole("heading", { level: 2 })).toContainText(headcode);
  await expect(panel.getByRole("listitem").first()).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`train=${train?.rid}`));

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();

  expect(errors).toEqual([]);
});
