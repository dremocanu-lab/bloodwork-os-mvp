"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export type UploadFormatCapability = {
  extension: string;
  mime_types: string[];
  supported: boolean;
  ocr_required: boolean;
  structured_parser: boolean;
  viewer_behavior: string;
  classification_supported: boolean;
};

export type UploadCapabilities = {
  accept: string;
  supportTextEn: string;
  supportTextRo: string;
  formats: UploadFormatCapability[];
};

// Used until GET /upload/capabilities resolves, and as a fail-open
// fallback if that call ever errors — never blocks upload on a network
// hiccup. Deliberately matches the backend's OWN allowlist as of this
// change (see app/services/ingestion/capability_registry.py) so the
// common case (fast path, capabilities endpoint already warm) never
// visibly differs from the fallback; a future format added to the
// registry without this constant being updated just means the accept
// attribute is very slightly stale for one request before the real
// fetch resolves, never a silent capability mismatch (the backend is
// always the real source of truth for what it will actually process).
const FALLBACK: UploadCapabilities = {
  accept:
    ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,.heic,.heif,.doc,.docx,.rtf,.odt,.txt,.md,.csv,.tsv,.xlsx,.ods,.json,.xml",
  supportTextEn:
    "PDF, Word documents, images, spreadsheets, and common health-record exports (CSV, XLSX, JSON, XML).",
  supportTextRo:
    "PDF, documente Word, imagini, foi de calcul și exporturi medicale uzuale (CSV, XLSX, JSON, XML).",
  formats: [],
};

function buildAccept(formats: UploadFormatCapability[]): string {
  return formats
    .filter((format) => format.supported)
    .map((format) => format.extension)
    .join(",");
}

let cachedCapabilities: UploadCapabilities | null = null;
let inFlightRequest: Promise<UploadCapabilities> | null = null;

async function fetchUploadCapabilities(): Promise<UploadCapabilities> {
  if (cachedCapabilities) return cachedCapabilities;
  if (inFlightRequest) return inFlightRequest;

  inFlightRequest = api
    .get<{ formats: UploadFormatCapability[] }>("/upload/capabilities")
    .then((response) => {
      const formats = response.data.formats || [];
      const accept = buildAccept(formats) || FALLBACK.accept;
      const result: UploadCapabilities = {
        accept,
        supportTextEn: FALLBACK.supportTextEn,
        supportTextRo: FALLBACK.supportTextRo,
        formats,
      };
      cachedCapabilities = result;
      return result;
    })
    .catch(() => FALLBACK)
    .finally(() => {
      inFlightRequest = null;
    });

  return inFlightRequest;
}

/** The upload picker's allowed types and support copy, derived from the
 * backend's own capability registry (GET /upload/capabilities) — see
 * that module's docstring. Falls back to a fixed, backend-matching
 * constant on first render (before the fetch resolves) and if the
 * request ever fails, so upload is never blocked by this call. */
export function useUploadCapabilities(): UploadCapabilities {
  const [capabilities, setCapabilities] = useState<UploadCapabilities>(cachedCapabilities ?? FALLBACK);

  useEffect(() => {
    let cancelled = false;
    fetchUploadCapabilities().then((result) => {
      if (!cancelled) setCapabilities(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return capabilities;
}
