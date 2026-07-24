"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { api, getToken, type MatrixParams } from "@/lib/api";
import { AppShell } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import { MatrixPane } from "@/components/workbench/MatrixPane";
import { CurrencyRateBar } from "@/components/workbench/CurrencyRateBar";
import { DutyStep } from "@/components/workbench/DutyStep";
import { InboxTab } from "@/components/workbench/InboxTab";
import { QuoteTab } from "@/components/workbench/QuoteTab";
import {
  WorkflowStepper,
  type WorkflowStep,
} from "@/components/workbench/WorkflowStepper";
import { useChat } from "@/contexts/ChatContext";
import { DeleteProjectButton } from "@/components/DeleteProjectButton";

const STEPS: (WorkflowStep & { blurb: string })[] = [
  {
    key: "upload",
    label: "Upload",
    blurb: "Add supplier quotes — PDFs, images, screenshots or pasted emails.",
  },
  {
    key: "duty",
    label: "Duty",
    blurb: "Confirm the items and assign HS codes so duties are calculated.",
  },
  {
    key: "matrix",
    label: "Compare",
    blurb: "Compare landed cost across suppliers in any currency.",
  },
  {
    key: "quote",
    label: "Quote",
    blurb: "Generate the customer quotation, then download it.",
  },
];

export default function WorkbenchPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const [step, setStep] = useState(0);
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

  // Opening a quote's source jumps back to the Upload step and opens the doc.
  function openSource(documentId: string) {
    setOpenDocId(documentId);
    setStep(0);
  }

  const current = STEPS[step];

  return (
    <AppShell fullHeight>
      <main className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6">
        <div className="mb-4 flex items-start gap-2">
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

        <div className="rounded-2xl border border-border/60 bg-card/40 p-3 shadow-soft sm:p-4">
          <WorkflowStepper steps={STEPS} current={step} onStep={setStep} />
          <p className="mt-3 px-1 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">
              Step {step + 1} of {STEPS.length}:
            </span>{" "}
            {current.blurb}
          </p>
        </div>

        <div className="mt-4">
          {current.key === "upload" && (
            <InboxTab
              projectId={id}
              openDocId={openDocId}
              onConsumeOpen={() => setOpenDocId(null)}
            />
          )}

          {current.key === "duty" && (
            <DutyStep projectId={id} params={params} onChange={setParams} />
          )}

          {current.key === "matrix" && (
            <div className="space-y-4">
              <CurrencyRateBar params={params} onChange={setParams} />
              <MatrixPane
                projectId={id}
                params={params}
                onOpenSource={openSource}
              />
            </div>
          )}

          {current.key === "quote" && (
            <QuoteTab projectId={id} onGoToBom={() => setStep(1)} />
          )}
        </div>

      </main>

      {/* Guided Back / Next — fixed bottom action bar */}
      <div className="shrink-0 border-t border-border bg-paper px-4 py-3 shadow-[0_-1px_4px_rgba(0,0,0,0.05)] sm:px-6">
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            <ArrowLeft className="h-4 w-4" /> Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}>
              Next: {STEPS[step + 1].label} <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <span className="text-sm text-muted-foreground">
              Last step — download your quote above.
            </span>
          )}
        </div>
      </div>
    </AppShell>
  );
}
