// Invoice duty calculator, end to end against the live stack (needs the
// backend on :8000 and Ollama, like the other e2e specs).
import { expect, test } from "@playwright/test";
import { authInit, uniqueEmail } from "./helpers";

const SHOTS = process.env.VERIFY_SHOTS_DIR ?? "test-results";

const INVOICE_TEXT = `COMMERCIAL INVOICE No. CI-2026-0788
Shenzhen Hongfa Machinery Co., Ltd
To: Mtech Engineering, Karachi, Pakistan
Currency: USD

Item 1: Hydraulic gear pump CBN-F540, 40cc displacement | Qty: 10 pcs | Unit Price: 60.00 | Amount: 600.00
Item 2: Pressure relief valve YF-B10H, brass body | Qty: 20 pcs | Unit Price: 20.00 | Amount: 400.00

Subtotal: 1,000.00
Sea Freight (Shanghai to Karachi): 100.00
TOTAL: USD 1,100.00`;

test("invoice tab: paste -> parse -> classify -> calculate", async ({
  page,
  request,
}) => {
  test.setTimeout(360_000);
  await authInit(page, request, uniqueEmail("duty"));
  await page.goto("/duty-calculator");

  // Single-item tab is the default and must still render its old UI.
  await expect(page.getByText("Auto-detect from a document")).toBeVisible();

  await page.getByRole("tab", { name: "Invoice / multi-item" }).click();
  await expect(page.getByText("Read an invoice or quotation")).toBeVisible();

  // FX auto-fetch fills the conversion rate.
  const fxInput = page.locator("#inv-fx");
  await expect(fxInput).not.toHaveValue("", { timeout: 20_000 });

  // Paste invoice text and read items (one real LLM call).
  await page.getByRole("tab", { name: "Paste text" }).click();
  await page.getByPlaceholder("Paste the invoice or quotation text here…").fill(INVOICE_TEXT);
  await page.getByRole("button", { name: "Read items" }).click();

  const hsInputs = page.getByPlaceholder("e.g. 8517.12.00");
  await expect(hsInputs).toHaveCount(2, { timeout: 120_000 });
  await expect(page.locator("#inv-freight")).toHaveValue(/^100(\.0+)?$/);

  // Sequential auto-classification fills each row's HS code.
  await expect(hsInputs.nth(0)).not.toHaveValue("", { timeout: 150_000 });
  await expect(hsInputs.nth(1)).not.toHaveValue("", { timeout: 150_000 });
  await page.screenshot({ path: `${SHOTS}/invoice-items.png`, fullPage: true });

  // Expand the first item's rate editor.
  await page.getByTitle("Edit duty rates for this item").first().click();
  await expect(page.getByText("Customs Duty %").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/invoice-rates.png`, fullPage: true });

  await page
    .getByRole("button", { name: "Calculate duties & landed price" })
    .click();
  await expect(page.getByText("Total landed cleared price")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("Invoice summary")).toBeVisible();
  await expect(page.getByText("Duties & taxes (Collector of Customs)")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/invoice-results.png`, fullPage: true });

  // Old single-item flow still works after switching back.
  await page.getByRole("tab", { name: "Single item" }).click();
  await expect(page.getByText("Auto-detect from a document")).toBeVisible();
  await expect(page.getByLabel("HS / PCT code")).toBeVisible();
});
