"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, RefreshCw, Search, Loader2, Trash2 } from "lucide-react";
import {
  api,
  getToken,
  type Tender,
  type TenderFilter,
  type TenderSource,
} from "@/lib/api";
import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/use-toast";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TenderDetailDrawer } from "@/components/tenders/TenderDetailDrawer";

const EMPTY: TenderFilter = {};

export default function TendersPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<TenderFilter>(EMPTY);
  const [applied, setApplied] = useState<TenderFilter>(EMPTY);
  const [selected, setSelected] = useState<Tender | null>(null);
  const [bgPulling, setBgPulling] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const tenders = useQuery({
    queryKey: ["tenders", applied],
    queryFn: () => api.listTenders(applied),
  });

  const sources = useQuery({
    queryKey: ["tender-sources"],
    queryFn: api.listSources,
  });

  const savedFilters = useQuery({
    queryKey: ["saved-filters"],
    queryFn: api.listSavedFilters,
  });

  const saveFilter = useMutation({
    mutationFn: (name: string) =>
      api.createSavedFilter(name, applied as Record<string, unknown>),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["saved-filters"] });
      qc.invalidateQueries({ queryKey: ["tender-badge"] });
      toast({ title: "Filter saved" });
    },
  });

  const deleteFilter = useMutation({
    mutationFn: (id: string) => api.deleteSavedFilter(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-filters"] }),
  });

  const hasFilters = useMemo(
    () => Object.values(applied).some((v) => v),
    [applied],
  );

  const enabledSources = useMemo(
    () => (sources.data ?? []).filter((s: TenderSource) => s.enabled),
    [sources.data],
  );

  const pullAllSources = useCallback(async () => {
    if (enabledSources.length === 0) {
      toast({ title: "No enabled sources to pull", variant: "destructive" });
      return;
    }
    setBgPulling(true);
    try {
      for (const source of enabledSources) {
        await api.pullSourceAsync(source.id);
      }
      toast({
        title: `Queued ${enabledSources.length} pull(s)`,
        description:
          "Running in the background — new tenders will appear here as they land. Safe to navigate away.",
      });
      qc.invalidateQueries({ queryKey: ["activity"] });
      // Refresh the list a few times while the background jobs run.
      setTimeout(() => qc.invalidateQueries({ queryKey: ["tenders"] }), 15_000);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["tenders"] }), 60_000);
    } catch {
      toast({ title: "Failed to queue pulls", variant: "destructive" });
    } finally {
      setBgPulling(false);
      qc.invalidateQueries({ queryKey: ["tender-sources"] });
    }
  }, [enabledSources, qc]);

  const cleanup = useMutation({
    mutationFn: () => api.cleanupTenders(),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["tenders"] });
      toast({
        title: res.removed
          ? `Removed ${res.removed} old tender(s), kept ${res.kept}`
          : "Nothing to clean up",
      });
    },
    onError: () => toast({ title: "Cleanup failed", variant: "destructive" }),
  });

  function apply() {
    const clean = Object.fromEntries(
      Object.entries(draft).filter(([, v]) => v),
    ) as TenderFilter;
    setApplied(clean);
  }

  return (
    <div className="min-h-screen">
      <AppNav />
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Tenders</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Public procurement notices from your sources
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={pullAllSources}
              disabled={bgPulling || enabledSources.length === 0}
            >
              {bgPulling ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {bgPulling
                ? "Queuing…"
                : `Pull all sources (${enabledSources.length})`}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                const total = tenders.data?.length ?? 0;
                const excess = Math.max(0, total - 50);
                if (
                  window.confirm(
                    excess
                      ? `Remove ~${excess} old tender(s) and keep the newest 50? Their embeddings and downloaded documents are deleted too.`
                      : "Keep only the newest 50 tenders? (Nothing may need removing right now.)",
                  )
                ) {
                  cleanup.mutate();
                }
              }}
              disabled={cleanup.isPending}
              className="gap-1.5 text-muted-foreground"
            >
              <Trash2 className="h-4 w-4" />
              Clean up old tenders
            </Button>
          </div>
        </div>

        {/* Saved-filter chips */}
        {(savedFilters.data?.length ?? 0) > 0 && (
          <div className="mb-4 flex flex-wrap gap-2">
            {savedFilters.data!.map((f) => (
              <button
                key={f.id}
                onClick={() => {
                  setApplied(f.criteria as TenderFilter);
                  setDraft(f.criteria as TenderFilter);
                }}
                onDoubleClick={() => deleteFilter.mutate(f.id)}
                title="Click to apply · double-click to delete"
                className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-accent/60 px-3 py-1 text-xs font-medium text-accent-foreground transition-all hover:bg-accent hover:shadow-soft"
              >
                <Bookmark className="h-3 w-3" /> {f.name}
              </button>
            ))}
          </div>
        )}

        {/* Filter bar */}
        <div className="mb-4 grid grid-cols-1 gap-2 rounded-xl border border-border/60 bg-card p-3 shadow-soft sm:grid-cols-2 md:grid-cols-4">
          <Input
            placeholder="Keyword"
            value={draft.keyword ?? ""}
            onChange={(e) => setDraft({ ...draft, keyword: e.target.value })}
          />
          <Input
            placeholder="Tender no"
            value={draft.tender_no ?? ""}
            onChange={(e) => setDraft({ ...draft, tender_no: e.target.value })}
          />
          <Input
            placeholder="Organization"
            value={draft.organization ?? ""}
            onChange={(e) => setDraft({ ...draft, organization: e.target.value })}
          />
          <Input
            placeholder="City"
            value={draft.city ?? ""}
            onChange={(e) => setDraft({ ...draft, city: e.target.value })}
          />
          <select
            className="select-base"
            value={draft.org_type ?? ""}
            onChange={(e) => setDraft({ ...draft, org_type: e.target.value })}
          >
            <option value="">Any org type</option>
            <option value="federal">Federal</option>
            <option value="provincial">Provincial</option>
            <option value="military">Military</option>
            <option value="soe">SOE</option>
            <option value="other">Other</option>
          </select>
          <select
            className="select-base"
            value={draft.category ?? ""}
            onChange={(e) => setDraft({ ...draft, category: e.target.value })}
          >
            <option value="">Any category</option>
            <option value="goods">Goods</option>
            <option value="works">Works</option>
            <option value="services">Services</option>
            <option value="consultancy">Consultancy</option>
          </select>
          <Input
            placeholder="Sector tag"
            value={draft.sector ?? ""}
            onChange={(e) => setDraft({ ...draft, sector: e.target.value })}
          />
          <select
            className="select-base"
            value={draft.status ?? ""}
            onChange={(e) => setDraft({ ...draft, status: e.target.value })}
          >
            <option value="">Any status</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
          <div className="flex flex-wrap items-center gap-2 sm:col-span-2 md:col-span-4">
            <Button onClick={apply} size="sm">
              <Search className="h-4 w-4" /> Search
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setDraft(EMPTY);
                setApplied(EMPTY);
              }}
            >
              Clear
            </Button>
            {hasFilters && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const name = window.prompt("Name this filter");
                  if (name) saveFilter.mutate(name);
                }}
              >
                <Bookmark className="h-4 w-4" /> Save filter
              </Button>
            )}
          </div>
        </div>

        {/* Results */}
        {tenders.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton h-12" />
            ))}
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-soft">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  <TableHead className="hidden sm:table-cell">Tender no</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead className="hidden md:table-cell">
                    Organization
                  </TableHead>
                  <TableHead className="hidden lg:table-cell">Category</TableHead>
                  <TableHead>Closing</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tenders.data?.map((t) => (
                  <TableRow
                    key={t.id}
                    className="cursor-pointer"
                    onClick={() => setSelected(t)}
                  >
                    <TableCell className="hidden font-mono text-xs sm:table-cell">
                      {t.tender_no ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-[16rem] sm:max-w-sm">
                      <span className="block truncate font-medium">{t.title}</span>
                      <span className="block truncate text-xs text-muted-foreground md:hidden">
                        {t.organization ?? ""}
                      </span>
                    </TableCell>
                    <TableCell className="hidden max-w-[14rem] truncate md:table-cell">
                      {t.organization ?? "—"}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      {t.category && <Badge variant="outline">{t.category}</Badge>}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {t.closing_date ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
                {tenders.data?.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-12 text-center text-muted-foreground"
                    >
                      No tenders. Add a source and pull, or adjust filters.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </main>

      <TenderDetailDrawer tender={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
