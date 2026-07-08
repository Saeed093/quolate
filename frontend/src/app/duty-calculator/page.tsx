"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Calculator } from "lucide-react";
import { getToken } from "@/lib/api";
import { AppShell } from "@/components/AppNav";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { InvoiceTab } from "./invoice-tab";

const DUTY_COUNTRIES = [{ value: "PK", label: "Pakistan" }] as const;

export default function DutyCalculatorPage() {
  const router = useRouter();
  const [country, setCountry] = useState<string>("PK");

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  return (
    <AppShell>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <div className="mb-1 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Calculator className="h-5 w-5 text-teal" />
            <h1 className="font-display text-2xl font-semibold tracking-tight">
              Duty &amp; Tax Calculator
            </h1>
          </div>
          <Select value={country} onValueChange={setCountry}>
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Country" />
            </SelectTrigger>
            <SelectContent>
              {DUTY_COUNTRIES.map((c) => (
                <SelectItem key={c.value} value={c.value}>
                  {c.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          Full landed-cost breakdown: Customs Duty, Additional Customs Duty,
          Regulatory Duty, Sales Tax, Additional Sales Tax, FED, and advance
          Income Tax — for a whole invoice, item by item.
        </p>

        <div className="mb-6 flex items-start gap-2 rounded-xl border border-verify/30 bg-verify/10 px-3.5 py-3 text-xs text-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-verify" />
          <p>
            This is a calculation aid based on ingested rate data, not a
            substitute for the actual statute/SRO text or a customs agent&apos;s
            WeBOC-assessed figure. Verify before relying on this for a
            client-facing quote or a filing.
          </p>
        </div>

        <InvoiceTab />
      </main>
    </AppShell>
  );
}
