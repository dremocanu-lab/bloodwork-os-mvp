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
  listConversations: () => api.get<AskBragiConversation[]>("/ask-bragi/conversations"),
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
