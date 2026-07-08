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

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.register(email, password, displayName || undefined);
      await api.login(email, password);
      router.push("/projects");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
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
            Create account
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Set up your Quolate instance login
          </p>
        </div>
        <Card className="border-border bg-card p-6 shadow-lift">
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-medium text-muted-foreground">
                Display name
              </label>
              <Input
                placeholder="Your name (optional)"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="rounded-xl"
              />
            </div>
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
                placeholder="Choose a password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="rounded-xl"
              />
            </div>
            {error && <p className="text-sm text-gap">{error}</p>}
            <Button type="submit" className="w-full rounded-xl" disabled={loading}>
              {loading ? "Creating..." : "Create account"}
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-ink hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
