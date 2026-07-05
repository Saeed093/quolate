import type { APIRequestContext, Page } from "@playwright/test";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Registers + logs in a fresh user via the API, then injects the JWT into
// localStorage so the app is authenticated on first navigation.
export async function authInit(
  page: Page,
  request: APIRequestContext,
  email: string,
  password = "password123",
): Promise<string> {
  await request.post(`${API}/auth/register`, {
    data: { email, password, display_name: "E2E" },
  });
  const res = await request.post(`${API}/auth/login`, {
    data: { email, password },
  });
  const body = await res.json();
  const token: string = body.access_token;
  await page.addInitScript((t) => {
    window.localStorage.setItem("quolate_token", t);
  }, token);
  return token;
}

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}_${Date.now()}_${Math.floor(Math.random() * 1000)}@test.com`;
}
