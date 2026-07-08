"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, getToken, type MatrixParams } from "@/lib/api";
import { AppShell } from "@/components/AppNav";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MatrixPane } from "@/components/workbench/MatrixPane";
import { AssumptionsStrip } from "@/components/workbench/AssumptionsStrip";
import { BomTab } from "@/components/workbench/BomTab";
import { InboxTab } from "@/components/workbench/InboxTab";
import { useChat } from "@/contexts/ChatContext";
import { DeleteProjectButton } from "@/components/DeleteProjectButton";

export default function WorkbenchPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState("matrix");
  const [openDocId, setOpenDocId] = useState<string | null>(null);
  const [params, setParams] = useState<MatrixParams>({ currency: "USD" });
  const chat = useChat();

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    chat.setProjectId(id);
    chat.setParams(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    chat.setParams(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => api.getProject(id),
    enabled: !!id,
  });

  useEffect(() => {
    if (project.data) {
      const d = project.data.landed_cost_defaults as Record<string, number>;
      setParams((p) => ({
        currency: p.currency ?? project.data!.base_currency,
        duty_pct: p.duty_pct ?? d?.duty_pct,
        freight_per_unit: p.freight_per_unit ?? d?.freight_per_unit,
        lc_pct: p.lc_pct ?? d?.lc_pct,
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.data]);

  const refreshMatrix = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["matrix", id] });
  }, [qc, id]);

  useEffect(() => {
    chat.setOnMatrixChanged(() => refreshMatrix);
    return () => chat.setOnMatrixChanged(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshMatrix]);

  function openSource(documentId: string) {
    setOpenDocId(documentId);
    setTab("inbox");
  }

  return (
    <AppShell fullHeight>
      <main className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6">
        <Tabs value={tab} onValueChange={setTab}>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="label-section">Workbench</p>
                <h1 className="truncate font-display text-xl font-semibold tracking-tight">
                  {project.data?.name ?? "Project"}
                </h1>
              </div>
              {project.data && (
                <DeleteProjectButton
                  projectId={id}
                  projectName={project.data.name}
                  onDeleted={() => {
                    if (chat.projectId === id) chat.setProjectId(null);
                    qc.invalidateQueries({ queryKey: ["projects"] });
                    router.push("/projects");
                  }}
                />
              )}
            </div>
            <TabsList className="w-full sm:w-auto">
              <TabsTrigger value="bom" className="flex-1 sm:flex-none">
                BOM
              </TabsTrigger>
              <TabsTrigger value="inbox" className="flex-1 sm:flex-none">
                Inbox
              </TabsTrigger>
              <TabsTrigger value="matrix" className="flex-1 sm:flex-none">
                Matrix
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="bom" className="mt-4">
            <BomTab projectId={id} />
          </TabsContent>

          <TabsContent value="inbox" className="mt-4">
            <InboxTab
              projectId={id}
              openDocId={openDocId}
              onConsumeOpen={() => setOpenDocId(null)}
            />
          </TabsContent>

          <TabsContent value="matrix" className="mt-4 space-y-4">
            <AssumptionsStrip params={params} onChange={setParams} />
            <MatrixPane
              projectId={id}
              params={params}
              onOpenSource={openSource}
            />
          </TabsContent>
        </Tabs>
      </main>
    </AppShell>
  );
}
