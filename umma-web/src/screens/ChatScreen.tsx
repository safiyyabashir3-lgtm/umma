import { useState, useRef, useEffect } from 'react';
import { Language, Message, DebugInfo } from '../types';
import { sendMessage } from '../services/api';
import { startListening, speak, stopSpeaking } from '../services/voice';
import MessageBubble from '../components/MessageBubble';
import TypingIndicator from '../components/TypingIndicator';
import EmergencyBanner from '../components/EmergencyBanner';
import AlertPopup from '../components/AlertPopup';
import './ChatScreen.css';

interface Props {
  language: Language;
  onLanguageToggle: () => void;
}

const USER_ID = (() => {
  let id = localStorage.getItem('umma_user_id');
  if (!id) {
    id = 'user_' + Math.random().toString(36).slice(2, 10);
    localStorage.setItem('umma_user_id', id);
  }
  return id;
})();

const UmmaIcon = () => (
  <svg viewBox="0 0 80 100" fill="none" className="chat-header__icon">
    <ellipse cx="40" cy="50" rx="30" ry="42" stroke="#C9A96E" strokeWidth="1.2" fill="none"/>
    <circle cx="40" cy="22" r="8" stroke="#1A3A2A" strokeWidth="1.5" fill="none"/>
    <path d="M32,30 Q28,50 30,65 Q40,70 50,65 Q52,50 48,30" stroke="#1A3A2A" strokeWidth="1.5" fill="none"/>
    <circle cx="40" cy="54" r="5" stroke="#1A3A2A" strokeWidth="1.2" fill="none"/>
    <path d="M30,45 Q35,58 40,60 Q45,58 50,45" stroke="#1A3A2A" strokeWidth="1.2" fill="none"/>
  </svg>
);

const MicIcon = ({ active }: { active: boolean }) => (
  <svg viewBox="0 0 24 24" fill="none" width="22" height="22">
    <rect x="9" y="2" width="6" height="12" rx="3"
      fill={active ? '#C62828' : 'none'}
      stroke={active ? '#C62828' : '#C9A96E'}
      strokeWidth="1.8"/>
    <path d="M5,11 C5,15.4 8.1,19 12,19 C15.9,19 19,15.4 19,11"
      stroke={active ? '#C62828' : '#C9A96E'}
      strokeWidth="1.8" strokeLinecap="round"/>
    <line x1="12" y1="19" x2="12" y2="22"
      stroke={active ? '#C62828' : '#C9A96E'}
      strokeWidth="1.8" strokeLinecap="round"/>
    <line x1="9" y1="22" x2="15" y2="22"
      stroke={active ? '#C62828' : '#C9A96E'}
      strokeWidth="1.8" strokeLinecap="round"/>
  </svg>
);

const SendIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" width="20" height="20">
    <path d="M22,2 L11,13" stroke="white" strokeWidth="2" strokeLinecap="round"/>
    <path d="M22,2 L15,22 L11,13 L2,9 Z" fill="white" stroke="white" strokeWidth="1.5"
      strokeLinejoin="round"/>
  </svg>
);

export default function ChatScreen({ language, onLanguageToggle }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [isEmergency, setIsEmergency] = useState(false);
  const [emergencyText, setEmergencyText] = useState('');
  const [showReviewer, setShowReviewer] = useState(false);
  const [debugHistory, setDebugHistory] = useState<DebugInfo[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [alertTier, setAlertTier] = useState<string | null>(null);
  const [alertDebug, setAlertDebug] = useState<DebugInfo | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognizerRef = useRef<any>(null);

  const welcomeText = language === 'en'
    ? 'Welcome to UMMA.\nHow may I help you?'
    : 'Sannu da zuwa UMMA.\nMe kikeson tambayata yau?';

  const placeholderText = language === 'en'
    ? 'Type your message...'
    : 'Rubuta saƙonki...';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
  };

  const processAndRespond = async (text: string, fromVoice: boolean) => {
    if (!text.trim() || isTyping) return;

    stopSpeaking();
    setIsSpeaking(false);

    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setInput('');
    setIsTyping(true);

    try {
      const data = await sendMessage(text, USER_ID, sessionId);
      if (data.session_id) setSessionId(data.session_id);
      if (data.debug) {
        setDebugHistory(prev => [...prev, data.debug]);
        const tier = data.debug?.action_tier;
        const concluded = data.debug?.concluded;
        if (concluded && tier) {
          setTimeout(() => {
            setAlertTier(tier);
            setAlertDebug(data.debug);
          }, 3000);
        }
      }

      if (data.debug?.action_tier === 'emergency') {
        setIsEmergency(true);
        setEmergencyText(language === 'en'
          ? 'EMERGENCY — Go to hospital immediately'
          : 'GAGGAWA — Je asibiti yanzu');
      }

      setMessages(prev => [...prev, { role: 'assistant', content: data.response }]);

      if (fromVoice && language === 'en') {
        setIsSpeaking(true);
        speak(data.response).finally(() => setIsSpeaking(false));
      }

    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: language === 'en'
          ? 'Something went wrong. Please try again.'
          : 'Wani abu ya kasa. Don Allah sake gwadawa.'
      }]);
    }

    setIsTyping(false);
  };

  const handleSend = () => {
    processAndRespond(input, false);
  };

  const handleMic = () => {
    if (language === 'ha') {
      setVoiceError('Zaki iya hira da UMMA a yaren Hausa ta murya anan gaba kadan!');
      setTimeout(() => setVoiceError(null), 4000);
      return;
    }

    if (isRecording) {
      recognizerRef.current?.close();
      setIsRecording(false);
      return;
    }

    setVoiceError(null);
    stopSpeaking();
    setIsSpeaking(false);
    setIsRecording(true);

    recognizerRef.current = startListening(
      (text: string) => {
        setIsRecording(false);
        processAndRespond(text, true);
      },
      (reason: string) => {
        console.error('Voice error:', reason);
        setIsRecording(false);
        setVoiceError('Could not hear you. Please try again.');
        setTimeout(() => setVoiceError(null), 3000);
      }
    );
  };

  const handleNewSession = () => {
    stopSpeaking();
    setMessages([]);
    setSessionId(null);
    setIsEmergency(false);
    setEmergencyText('');
    setDebugHistory([]);
    setAlertTier(null);
    setAlertDebug(null);
    setIsSpeaking(false);
    setVoiceError(null);
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-screen">
      <header className="chat-header">
        <div className="chat-header__left">
          <UmmaIcon />
          <span className="chat-header__wordmark">UMMA</span>
        </div>
        <div className="chat-header__actions">
          {isSpeaking && <span className="chat-speaking-indicator">◉ speaking</span>}
          <button
            className="chat-header__btn chat-header__btn--lang"
            onClick={onLanguageToggle}
          >
            {language === 'en' ? 'HA' : 'EN'}
          </button>
          <button className="chat-header__btn" onClick={() => setShowReviewer(true)}>Review</button>
          <button className="chat-header__btn" onClick={handleNewSession}>New</button>
        </div>
      </header>

      <div className="chat-header__divider">
        <span className="chat-header__divider__line" />
        <span className="chat-header__divider__diamond">✦</span>
        <span className="chat-header__divider__line" />
      </div>

      {isEmergency && <EmergencyBanner text={emergencyText} />}
      {alertTier && alertDebug && sessionId && (
        <AlertPopup
          actionTier={alertTier}
          debugInfo={alertDebug}
          sessionId={sessionId}
          userId={USER_ID}
          language={language}
          onDismiss={() => { setAlertTier(null); setAlertDebug(null); }}
        />
      )}
      {voiceError && <div className="chat-voice-error">{voiceError}</div>}

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p className="chat-empty__welcome">{welcomeText}</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}
        {isTyping && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-area">
        <button
          className={`chat-mic-btn ${isRecording ? 'chat-mic-btn--recording' : ''}`}
          onClick={handleMic}
        >
          <MicIcon active={isRecording} />
        </button>
        <input
          className="chat-input"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKey}
          placeholder={isRecording ? 'Listening...' : placeholderText}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!input.trim() || isTyping}
        >
          <SendIcon />
        </button>
      </div>

      {showReviewer && (
        <div className="reviewer-overlay">
          <div className="reviewer-header">
            <span>Clinical Review</span>
            <button onClick={() => setShowReviewer(false)}>✕</button>
          </div>
          <div className="reviewer-body">
            {debugHistory.length === 0 && (
              <p style={{ color: '#888', padding: '16px' }}>No turns yet.</p>
            )}
            {[...debugHistory].reverse().map((d, i) => (
              <div className="reviewer-card" key={i}>
                <div className="reviewer-card__header">
                  Turn {debugHistory.length - i} &nbsp;
                  <span className={`stage-badge stage-badge--${d.stage}`}>{d.stage}</span>
                </div>
                <div className="reviewer-field">
                  <div className="reviewer-label">Symptoms</div>
                  <div className="reviewer-value">{d.reported_symptoms?.join(', ') || '—'}</div>
                </div>
                <div className="reviewer-field">
                  <div className="reviewer-label">Internal Diagnosis</div>
                  <div className="reviewer-value">{d.internal_diagnosis || '—'}</div>
                </div>
                <div className="reviewer-field">
                  <div className="reviewer-label">Confidence · Action Tier</div>
                  <div className="reviewer-value">{d.confidence_level || '—'} · {d.action_tier || '—'}</div>
                </div>
                <div className="reviewer-field">
                  <div className="reviewer-label">Differentials</div>
                  <div className="reviewer-value">
                    {d.active_differentials?.map((diff, j) => (
                      <div key={j} className={`diff diff--${diff.confidence}`}>
                        <strong>{diff.condition}</strong> — {diff.confidence}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="reviewer-field">
                  <div className="reviewer-label">Files Retrieved</div>
                  <div className="reviewer-value">
                    {d.retrieval_log?.map((r, j) => (
                      <div key={j}><em>{r.category}:</em> {r.files?.join(', ')}</div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
