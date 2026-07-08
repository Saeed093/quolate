"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";

export function DeleteProjectButton({
  projectId,
  projectName,
  onDeleted,
  variant = "ghost",
  className,
}: {
  projectId: string;
  projectName: string;
  onDeleted?: () => void;
  variant?: "ghost" | "outline" | "destructive";
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  const del = useMutation({
    mutationFn: () => api.deleteProject(projectId),
    onSuccess: () => {
      setOpen(false);
      toast({ title: `Deleted “${projectName}”` });
      onDeleted?.();
    },
    onError: () =>
      toast({ title: "Could not delete project", variant: "destructive" }),
  });

  return (
    <>
      <Button
        type="button"
        size="icon"
        variant={variant}
        className={cn("h-8 w-8 shrink-0 text-muted-foreground hover:text-gap", className)}
        aria-label={`Delete ${projectName}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        <Trash2 className="h-4 w-4" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md" onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Delete project?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{projectName}</span> and
            all of its BOM lines, suppliers, uploaded documents, quotes, and chat
            history will be permanently removed. This cannot be undone.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={del.isPending}
              onClick={() => del.mutate()}
            >
              {del.isPending ? "Deleting…" : "Delete project"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
