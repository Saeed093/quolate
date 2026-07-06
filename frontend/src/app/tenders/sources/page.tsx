"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2, Loader2 } from "lucide-react";
import { api, getToken, type TenderSource } from "@/lib/api";
import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/use-toast";

const ADAPTERS = [
  "generic",
  "ppra_federal",
  "ppra_punjab",
  "ppra_sindh",
  "ppra_kpk",
];

export default function SourcesPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [adapter, setAdapter] = useState("generic");

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const [bgPulling, setBgPulling] = useState<Set<string>>(new Set());

  const sources = useQuery({
    queryKey: ["tender-sources"],
    queryFn: api.listSources,
    // Refresh source status while a background pull is queued/running.
    refetchInterval: bgPulling.size > 0 ? 10_000 : false,
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["tender-sources"] });

  const create = useMutation({
    mutationFn: () => api.createSource(name, url, adapter),
    onSuccess: () => {
      setName("");
      setUrl("");
      setAdapter("generic");
      invalidate();
      toast({ title: "Source added" });
    },
  });

  const toggle = useMutation({
    mutationFn: (s: TenderSource) =>
      api.updateSource(s.id, { enabled: !s.enabled }),
    onSuccess: invalidate,
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteSource(id),
    onSuccess: invalidate,
  });

  const pullInBackground = useMutation({
    mutationFn: (id: string) => api.pullSourceAsync(id),
    onSuccess: (_data, id) => {
      setBgPulling((prev) => new Set(prev).add(id));
      qc.invalidateQueries({ queryKey: ["activity"] });
      toast({
        title: "Pull queued",
        description:
          "Running in the background — you can navigate away. Status updates on this page.",
      });
    },
    onError: () => toast({ title: "Failed to queue pull", variant: "destructive" }),
  });

  // Once a source's last_run changes to a fresh value, drop it from bgPulling.
  useEffect(() => {
    if (bgPulling.size === 0 || !sources.data) return;
    const now = Date.now();
    setBgPulling((prev) => {
      const next = new Set(prev);
      for (const s of sources.data) {
        if (
          next.has(s.id) &&
          s.last_run &&
          now - new Date(s.last_run).getTime() < 60_000
        ) {
          next.delete(s.id);
          qc.invalidateQueries({ queryKey: ["tenders"] });
          qc.invalidateQueries({ queryKey: ["tender-badge"] });
        }
      }
      return next.size === prev.size ? prev : next;
    });
  }, [sources.data, bgPulling.size, qc]);

  return (
    <div className="min-h-screen">
      <AppNav />
      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <div className="mb-5">
          <h1 className="text-2xl font-semibold tracking-tight">
            Tender sources
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Portals Quolate scrapes for new tender notices
          </p>
        </div>

        <Card className="mb-6 shadow-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Add a source</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[1fr_1.5fr_auto_auto]"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim() && url.trim()) create.mutate();
              }}
            >
              <Input
                placeholder="Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <Input
                placeholder="https://portal.example/tenders"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <select
                className="select-base lg:w-36"
                value={adapter}
                onChange={(e) => setAdapter(e.target.value)}
              >
                {ADAPTERS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
              <Button type="submit" disabled={create.isPending}>
                Add
              </Button>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-2">
          {sources.data?.map((s) => (
            <div
              key={s.id}
              className="flex flex-col gap-3 rounded-xl border border-border/60 bg-card p-3.5 shadow-soft lg:flex-row lg:items-center lg:gap-4"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{s.name}</span>
                  <Badge variant="outline">{s.adapter}</Badge>
                  {s.enabled ? (
                    <Badge variant="ok">enabled</Badge>
                  ) : (
                    <Badge variant="secondary">disabled</Badge>
                  )}
                  {s.last_status === "failed" && (
                    <Badge variant="gap">last run failed</Badge>
                  )}
                  {s.last_status === "ok" && (
                    <Badge variant="ok">last run ok</Badge>
                  )}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {s.base_url}
                  {s.last_run
                    ? ` · last run ${new Date(s.last_run).toLocaleString()}`
                    : " · never run"}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => pullInBackground.mutate(s.id)}
                  disabled={bgPulling.has(s.id) || pullInBackground.isPending}
                  title="Runs in the background — safe to navigate away"
                >
                  {bgPulling.has(s.id) ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  {bgPulling.has(s.id) ? "Pulling…" : "Pull"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => toggle.mutate(s)}
                >
                  {s.enabled ? "Disable" : "Enable"}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => del.mutate(s.id)}
                  aria-label="Delete source"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
          {sources.data?.length === 0 && (
            <div className="rounded-2xl border border-dashed border-border py-12 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                <RefreshCw className="h-5 w-5 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No sources yet</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Add a portal URL above to start tracking tenders.
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
