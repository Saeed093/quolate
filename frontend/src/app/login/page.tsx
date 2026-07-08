"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { QuolateLockup } from "@/components/QuolateLockup";
import { BRAND_TAGLINE } from "@/lib/brand";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(email, password);
      router.push("/projects");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden gradient-auth px-4">
      <div className="dot-grid absolute inset-0" aria-hidden />
      <div className="relative w-full max-w-sm animate-fade-in-up">
        <div className="mb-8 flex flex-col items-center text-center">
          <QuolateLockup variant="light" className="mb-4" />
          <p className="font-mono text-xs uppercase tracking-wider text-slate-soft">
            {BRAND_TAGLINE}
          </p>
          <h1 className="mt-5 font-display text-2xl font-semibold tracking-tight">
            Welcome back
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sign in to your Quolate workbench
          </p>
        </div>
        <Card className="border-border bg-card p-6 shadow-lift">
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground">
                Email
              </label>
              <Input
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground">
                Password
              </label>
              <Input
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="rounded-xl"
              />
            </div>
            {error && <p className="text-sm text-gap">{error}</p>}
            <Button type="submit" className="w-full rounded-xl" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          No account?{" "}
          <Link
            href="/register"
            className="font-medium text-ink hover:underline"
          >
            Register
          </Link>
        </p>
      </div>
    </main>
  );
}
