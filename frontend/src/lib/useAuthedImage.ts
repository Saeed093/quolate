"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/api";

// Page-image and original-file endpoints require the JWT in a header, so a plain
// <img src> won't authenticate. This fetches the resource as a blob URL.
export function useAuthedImage(url: string | null): {
  src: string | null;
  loading: boolean;
  error: boolean;
} {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!url) {
      setSrc(null);
      return;
    }
    let objectUrl: string | null = null;
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetch(url, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => !cancelled && setError(true))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  return { src, loading, error };
}
