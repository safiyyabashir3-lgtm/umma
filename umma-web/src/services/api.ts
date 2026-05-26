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
