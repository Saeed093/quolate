"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api, getToken, type ActivitySummary } from "@/lib/api";

export interface UploadActivity {
  id: string;
  label: string;
  percent: number | null;
}

interface ActivityContextValue {
  uploads: UploadActivity[];
  activity: ActivitySummary | undefined;
  startUpload: (id: string, label: string) => void;
  setUploadProgress: (id: string, percent: number) => void;
  endUpload: (id: string) => void;
  hasBackgroundActivity: boolean;
}

const ActivityContext = createContext<ActivityContextValue | null>(null);

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [uploads, setUploads] = useState<UploadActivity[]>([]);
  const uploadsRef = useRef(uploads);
  uploadsRef.current = uploads;

  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: api.getActivity,
    enabled: !!getToken(),
    refetchInterval: (q) => {
      const data = q.state.data as ActivitySummary | undefined;
      const serverBusy =
        (data?.documents_processing ?? 0) > 0 ||
        (data?.tender_pulls?.length ?? 0) > 0;
      const clientBusy = uploadsRef.current.length > 0;
      return serverBusy || clientBusy ? 3_000 : 15_000;
    },
  });

  const startUpload = useCallback((id: string, label: string) => {
    setUploads((prev) => {
      const rest = prev.filter((u) => u.id !== id);
      return [...rest, { id, label, percent: 0 }];
    });
  }, []);

  const setUploadProgress = useCallback((id: string, percent: number) => {
    setUploads((prev) =>
      prev.map((u) => (u.id === id ? { ...u, percent } : u)),
    );
  }, []);

  const endUpload = useCallback((id: string) => {
    setUploads((prev) => prev.filter((u) => u.id !== id));
  }, []);

  const hasBackgroundActivity = useMemo(() => {
    const data = activity.data;
    return (
      uploads.length > 0 ||
      (data?.documents_processing ?? 0) > 0 ||
      (data?.tender_pulls?.length ?? 0) > 0
    );
  }, [uploads.length, activity.data]);

  const value = useMemo(
    () => ({
      uploads,
      activity: activity.data,
      startUpload,
      setUploadProgress,
      endUpload,
      hasBackgroundActivity,
    }),
    [
      uploads,
      activity.data,
      startUpload,
      setUploadProgress,
      endUpload,
      hasBackgroundActivity,
    ],
  );

  return (
    <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>
  );
}

export function useActivity() {
  const ctx = useContext(ActivityContext);
  if (!ctx) {
    throw new Error("useActivity must be used within ActivityProvider");
  }
  return ctx;
}
