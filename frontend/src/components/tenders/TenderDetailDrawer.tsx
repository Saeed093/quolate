"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Tender } from "@/lib/api";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { formatCurrency } from "@/lib/format";

export function TenderDetailDrawer({
  tender,
  onClose,
}: {
  tender: Tender | null;
  onClose: () => void;
}) {
  const matches = useQuery({
    queryKey: ["tender-matches", tender?.id],
    queryFn: () => api.tenderMatches(tender!.id),
    enabled: !!tender,
  });

  return (
    <Sheet open={!!tender} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="max-w-xl">
        {tender && (
          <>
            <SheetHeader>
              <SheetTitle>{tender.title ?? tender.tender_no ?? "Tender"}</SheetTitle>
            </SheetHeader>

            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap gap-2">
                {tender.org_type && (
                  <Badge variant="secondary">{tender.org_type}</Badge>
                )}
                {tender.category && (
                  <Badge variant="outline">{tender.category}</Badge>
                )}
                {tender.corrigendum_of && (
                  <Badge variant="verify">corrigendum</Badge>
                )}
              </div>

              <dl className="space-y-1.5">
                <Row k="Tender no" v={tender.tender_no ?? "—"} />
                <Row k="Organization" v={tender.organization ?? "—"} />
                <Row k="City" v={tender.city ?? "—"} />
                <Row k="Closing" v={tender.closing_date ?? "—"} />
                <Row k="Advertised" v={tender.advertise_date ?? "—"} />
              </dl>

              {tender.sector_tags && tender.sector_tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tender.sector_tags.map((t) => (
                    <Badge key={t} variant="outline">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}

              <div>
                <h4 className="mb-2 font-semibold">Matches from your quotes</h4>
                {matches.isLoading && (
                  <p className="text-muted-foreground">Finding matches…</p>
                )}
                {matches.data && matches.data.count === 0 && (
                  <p className="text-muted-foreground">
                    No similar quotes in your projects yet.
                  </p>
                )}
                {matches.data && matches.data.count > 0 && (
                  <>
                    <p className="mb-2 text-muted-foreground">
                      You hold {matches.data.count} quote(s) for similar items.
                    </p>
                    <div className="space-y-2">
                      {matches.data.matches.map((m) => (
                        <div
                          key={m.document_id}
                          className="rounded-md border border-border p-2"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-medium">
                              {m.supplier ?? "Supplier"}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {Math.round(m.similarity * 100)}% match
                            </span>
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {m.item}
                          </div>
                          {m.unit_price !== null && (
                            <div className="mt-1 text-xs">
                              {formatCurrency(m.unit_price, m.currency ?? "USD")}
                              {m.date ? ` · ${m.date}` : ""}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-right font-medium">{v}</dd>
    </div>
  );
}
