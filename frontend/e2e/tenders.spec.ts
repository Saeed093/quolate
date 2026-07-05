import { test, expect } from "@playwright/test";
import { authInit, uniqueEmail } from "./helpers";

test.describe("tenders", () => {
  test("add a source, pull it, then filter and save a filter", async ({
    page,
    request,
  }) => {
    await authInit(page, request, uniqueEmail());

    // Add a source.
    await page.goto("/tenders/sources");
    await page.getByPlaceholder("Name").fill("E2E Source");
    await page
      .getByPlaceholder(/portal\.example/)
      .fill("https://example.com/");
    await page.getByRole("button", { name: "Add" }).click();
    await expect(page.getByText("E2E Source")).toBeVisible();

    // Pull now: wait until the source is no longer "never run" (ok or failed).
    await page.getByRole("button", { name: /Pull now/ }).click();
    await expect(page.getByText(/last run (ok|failed)/i)).toBeVisible({
      timeout: 90_000,
    });

    // Tenders list: filter UI works and a filter can be saved as a chip.
    await page.goto("/tenders");
    await expect(page.getByRole("button", { name: /Search/ })).toBeVisible();
    await page.getByPlaceholder("Keyword").fill("camera");
    await page.getByRole("button", { name: /Search/ }).click();

    page.once("dialog", (dialog) => dialog.accept("Cameras"));
    await page.getByRole("button", { name: /Save filter/ }).click();
    await expect(page.getByRole("button", { name: "Cameras" })).toBeVisible();
  });
});
