import { api } from "@/lib/api";

export type AskBragiCitation = {
  source_evidence_id: number;
  label: string;
  document_type?: string | null;
  date?: string | null;
  page?: number | null;
};

export type AskBragiChartPoint = {
  date: string | null;
  value: string | null;
  unit: string | null;
  flag: string | null;
  reference_range: string | null;
  /** Real row identity (not just a citation id) — lets the chart reuse
   * the exact same source-viewer entry point a lab table row's own
   * "View in original" action uses. */
  document_id: number | null;
  lab_result_id: number | null;
  source_evidence_id: number | null;
};

export type AskBragiChart = {
  canonical_name: string;
  points: AskBragiChartPoint[];
};

export type AskBragiScope = "patient_record" | "document";

export type AskBragiMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: AskBragiCitation[];
  chart: AskBragiChart | null;
  follow_ups: string[];
  status: string | null;
  /** The scope THIS TURN actually used — can be "patient_record" even in
   * a document-scoped conversation when the turn was visibly broadened
   * (see BRAGI_ASK_BRAGI_PLAN.md's scope-broadening section). Null on
   * optimistic (not-yet-server-confirmed) user messages. */
  scope_used?: AskBragiScope | null;
  created_at: string;
};

export type AskBragiConversation = {
  id: number;
  public_id: string | null;
  patient_id: number;
  scope: AskBragiScope;
  document_id: number | null;
  title: string | null;
  created_at: string;
  updated_at: string | null;
};

export type AskBragiConversationDetail = AskBragiConversation & {
  messages: AskBragiMessage[];
};

export const askBragiApi = {
  listConversations: (patientId?: number) =>
    api.get<AskBragiConversation[]>("/ask-bragi/conversations", { params: patientId ? { patient_id: patientId } : undefined }),
  createConversation: (payload: { patient_id?: number; document_id?: number }) =>
    api.post<AskBragiConversation>("/ask-bragi/conversations", payload),
  getConversation: (id: number) => api.get<AskBragiConversationDetail>(`/ask-bragi/conversations/${id}`),
  deleteConversation: (id: number) => api.delete(`/ask-bragi/conversations/${id}`),
  sendMessage: (id: number, message: string, requestedScope?: AskBragiScope) =>
    api.post<AskBragiMessage>(`/ask-bragi/conversations/${id}/messages`, {
      message,
      requested_scope: requestedScope,
    }),
};

/** One decoded Server-Sent Event frame from POST .../messages/stream —
 * see backend/app/main.py's stream_ask_bragi_message for exactly what
 * each event name carries. `data` is intentionally untyped here (each
 * handler below narrows it) rather than a discriminated union, since
 * the raw wire shape is plain JSON per event with no shared tag field. */
export type AskBragiStreamEvent = { event: string; data: Record<string, unknown> };

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "https://bloodwork-os-api.onrender.com").replace(/\/+$/, "");

/** Real streaming consumption: a raw fetch (axios has no first-class SSE
 * support for POST) reading the response body incrementally and
 * splitting it into SSE frames as bytes arrive — never buffering the
 * whole response before showing anything. `signal` is how Stop actually
 * cancels the underlying connection (see ask-bragi-chat.tsx). */
export async function streamAskBragiMessage(
  conversationId: number,
  message: string,
  requestedScope: AskBragiScope | undefined,
  onEvent: (event: AskBragiStreamEvent) => void,
  signal: AbortSignal
): Promise<void> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const response = await fetch(`${API_BASE}/ask-bragi/conversations/${conversationId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message, requested_scope: requestedScope }),
    signal,
  });

  if (!response.ok || !response.body) {
    let detail = "";
    try {
      const body = await response.json();
      detail = body?.detail || "";
    } catch {
      // Non-JSON error body — fall through to the generic message.
    }
    throw new Error(detail || `Ask Bragi could not process this message (${response.status}).`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let eventName = "";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) eventName = line.slice("event: ".length);
        else if (line.startsWith("data: ")) dataLine = line.slice("data: ".length);
      }
      if (eventName) {
        try {
          onEvent({ event: eventName, data: JSON.parse(dataLine || "{}") });
        } catch {
          // A malformed frame is dropped, not fatal to the rest of the stream.
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
