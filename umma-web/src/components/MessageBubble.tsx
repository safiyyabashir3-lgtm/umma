import { Message } from '../types';
import './MessageBubble.css';

interface Props {
  message: Message;
}

const UmmaAvatar = () => (
  <svg viewBox="0 0 80 100" fill="none" className="bubble-avatar">
    <circle cx="40" cy="40" r="38" fill="#1A3A2A"/>
    <ellipse cx="40" cy="42" rx="22" ry="30" stroke="#C9A96E" strokeWidth="1" fill="none"/>
    <circle cx="40" cy="24" r="6" stroke="#F5EFE4" strokeWidth="1.2" fill="none"/>
    <path d="M34,30 Q31,42 33,52 Q40,56 47,52 Q49,42 46,30" stroke="#F5EFE4" strokeWidth="1.2" fill="none"/>
    <circle cx="40" cy="44" r="4" stroke="#F5EFE4" strokeWidth="1" fill="none"/>
  </svg>
);

function getTime() {
  const now = new Date();
  return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  const time = getTime();

  if (isUser) {
    return (
      <div className="bubble-wrap bubble-wrap--user">
        <div className="bubble bubble--user">
          {message.content}
          <span className="bubble-time bubble-time--user">{time} ✓✓</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bubble-wrap bubble-wrap--umma">
      <UmmaAvatar />
      <div className="bubble bubble--umma">
        {message.content}
        <span className="bubble-time bubble-time--umma">{time}</span>
      </div>
    </div>
  );
}
