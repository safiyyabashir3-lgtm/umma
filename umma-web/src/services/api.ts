import axios from 'axios';
import { ChatResponse } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export async function sendMessage(
  message: string,
  userId: string,
  sessionId: string | null
): Promise<ChatResponse> {
  const body: Record<string, string> = { message, user_id: userId };
  if (sessionId) body.session_id = sessionId;
  const res = await axios.post<ChatResponse>(`${API_BASE}/chat`, body);
  return res.data;
}

export interface AlertRequest {
  alert_type: 'emergency' | 'urgent_clinic' | 'chw';
  session_id: string;
  user_id: string;
  action_tier: string;
  reported_symptoms: string[];
  internal_diagnosis?: string | null;
  active_differentials?: object[];
  language: string;
  worker_role?: 'chew' | 'nurse' | 'midwife';
  patient_name?: string;
  patient_age?: string;
}

export interface AlertResponse {
  success: boolean;
  message: string;
  recipients: { name: string; success: boolean }[];
  umma_ref?: string;
}

export async function sendAlert(payload: AlertRequest): Promise<AlertResponse> {
  const res = await axios.post<AlertResponse>(`${API_BASE}/alert`, payload);
  return res.data;
}
