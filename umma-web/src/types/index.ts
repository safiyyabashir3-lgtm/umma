export type Language = 'en' | 'ha';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface Differential {
  condition: string;
  confidence: 'high' | 'moderate' | 'low';
  supporting_evidence: string;
}

export interface DebugInfo {
  stage: string;
  questions_asked: number;
  internal_diagnosis: string;
  secondary_diagnosis: string;
  active_differentials: Differential[];
  confidence_level: string;
  action_tier: string;
  reported_symptoms: string[];
  symptom_topic: string;
  concluded: boolean;
  question_rationale: string;
  retrieval_log: { category: string; files: string[] }[];
}

export interface ChatResponse {
  intent: string;
  response: string;
  session_id: string;
  debug: DebugInfo;
}
