"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, FolderOpen, ArrowRight } from "lucide-react";
import { api, ApiError, getToken } from "@/lib/api";
import { AppNav } from "@/components/AppNav";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function ProjectsPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });

  const create = useMutation({
    mutationFn: (n: string) => api.createProject(n),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  if (projects.error instanceof ApiError && projects.error.status === 401) {
    router.replace("/login");
  }

  return (
    <div className="min-h-screen">
      <AppNav />
      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6 sm:py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Your sourcing workbenches
          </p>
        </div>

        <Card className="mb-6 p-4 shadow-card">
          <form
            className="flex flex-col gap-2 sm:flex-row"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) create.mutate(name.trim());
            }}
          >
            <Input
              placeholder="New project name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="rounded-xl"
            />
            <Button
              type="submit"
              disabled={create.isPending}
              className="shrink-0 gap-1.5 rounded-xl gradient-primary text-white hover:shadow-glow"
            >
              <Plus className="h-4 w-4" />
              Create
            </Button>
          </form>
        </Card>

        {projects.isLoading && (
          <div className="grid gap-3 sm:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-20" />
            ))}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          {projects.data?.map((p) => (
            <Card
              key={p.id}
              className="card-interactive group flex cursor-pointer items-center gap-3 p-4"
              onClick={() => router.push(`/projects/${p.id}`)}
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent transition-colors group-hover:gradient-primary">
                <FolderOpen className="h-[18px] w-[18px] text-accent-foreground transition-colors group-hover:text-white" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{p.name}</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {p.base_currency} · {p.status}
                </div>
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground/40 transition-all group-hover:translate-x-0.5 group-hover:text-primary" />
            </Card>
          ))}
        </div>

        {projects.data?.length === 0 && (
          <div className="rounded-2xl border border-dashed border-border py-16 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <FolderOpen className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium">No projects yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Create one above to get started.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
