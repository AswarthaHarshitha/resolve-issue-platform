export interface AIAnalysisResult {
  id: string;
  attempt_number: number;
  status: "COMPLETED" | "FAILED";
  raw_category: string | null;
  raw_sub_category: string | null;
  raw_priority: string | null;
  summary: string | null;
  reasoning: string | null;
  matched_priority: string | null;
  error_message: string | null;
  created_at: string;
}
