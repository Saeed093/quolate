import { test, expect } from "@playwright/test";
import { authInit, uniqueEmail } from "./helpers";

test.describe("workbench", () => {
  test("create project, paste BOM, view matrix, adjust assumptions, export", async ({
    page,
    request,
  }) => {
    await authInit(page, request, uniqueEmail());

    await page.goto("/projects");
    await page.getByPlaceholder("New project name").fill("E2E Project");
    await page.getByRole("button", { name: "Create" }).click();
    await page.getByText("E2E Project").click();

    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+/);

    // Duty step: paste two lines from "Excel" into the item editor.
    await page.getByRole("button", { name: "Duty" }).click();
    await page
      .getByPlaceholder(/Paste tab-separated/)
      .fill("Thermal Camera\t640x480\t100\t1200\nTripod\tAluminium\t50\t40");
    await page.getByRole("button", { name: /Import/ }).click();
    // The imported line renders as an editable input inside the item grid.
    await expect(
      page.locator("table tbody input").first(),
    ).toHaveValue("Thermal Camera");

    // Adjust the fallback duty assumption on the Duty step.
    const duty = page.getByLabel("Duty percent");
    await duty.fill("12");
    await duty.blur();
    await expect(duty).toHaveValue("12");

    // Compare step renders both BOM lines in the matrix.
    await page.getByRole("button", { name: "Compare" }).click();
    await expect(page.getByTestId("matrix-table")).toBeVisible();
    await expect(page.getByText("1. Thermal Camera")).toBeVisible();
    await expect(page.getByText("2. Tripod")).toBeVisible();

    // Export the matrix as XLSX.
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: /Export XLSX/ }).click(),
    ]);
    expect(download.suggestedFilename()).toContain(".xlsx");
  });

  test("upload a quote appears in the inbox", async ({ page, request }) => {
    await authInit(page, request, uniqueEmail());

    await page.goto("/projects");
    await page.getByPlaceholder("New project name").fill("Inbox Project");
    await page.getByRole("button", { name: "Create" }).click();
    await page.getByText("Inbox Project").click();

    // Upload is the first step of the guided flow, so the dropzone is already shown.
    await page.locator('input[type="file"]').setInputFiles({
      name: "quote.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "ACME Co\nThermal Camera unit price 1150 USD\nMOQ 100 units\nLead time 30 days",
      ),
    });

    await expect(page.getByText("quote.txt")).toBeVisible();
  });
});
