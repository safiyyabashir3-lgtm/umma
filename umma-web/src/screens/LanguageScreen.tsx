import { Language } from '../types';
import './LanguageScreen.css';

interface Props {
  onSelect: (lang: Language) => void;
}

export default function LanguageScreen({ onSelect }: Props) {
  return (
    <div className="lang-screen">

      <svg className="lang-wave lang-wave--top" viewBox="0 0 400 300" preserveAspectRatio="none">
        <path d="M0,0 Q150,180 400,60 L400,0 Z" fill="#2B6B4A" opacity="0.18"/>
      </svg>
      <svg className="lang-wave lang-wave--bottom" viewBox="0 0 400 300" preserveAspectRatio="none">
        <path d="M0,300 Q200,120 400,240 L400,300 Z" fill="#2B6B4A" opacity="0.22"/>
      </svg>

      <svg className="lang-leaf" viewBox="0 0 120 200" fill="none">
        <path d="M60,190 C60,190 10,140 20,80 C30,20 60,10 60,10 C60,10 90,20 100,80 C110,140 60,190 60,190Z" fill="#2B6B4A" opacity="0.13"/>
        <path d="M60,10 L60,190" stroke="#2B6B4A" strokeWidth="1.5" opacity="0.15"/>
        <path d="M60,60 Q80,70 95,65" stroke="#2B6B4A" strokeWidth="1" opacity="0.12"/>
        <path d="M60,90 Q80,100 98,90" stroke="#2B6B4A" strokeWidth="1" opacity="0.12"/>
        <path d="M60,120 Q78,130 94,122" stroke="#2B6B4A" strokeWidth="1" opacity="0.12"/>
        <path d="M60,60 Q40,70 25,65" stroke="#2B6B4A" strokeWidth="1" opacity="0.12"/>
        <path d="M60,90 Q40,100 22,90" stroke="#2B6B4A" strokeWidth="1" opacity="0.12"/>
        <path d="M60,120 Q42,130 26,122" stroke="#2B6B4A" strokeWidth="1" opacity="0.12"/>
      </svg>

      <div className="lang-content">

        <div className="lang-icon-wrap">
          <svg viewBox="0 0 80 100" fill="none" width="64" height="80">
            <ellipse cx="40" cy="50" rx="30" ry="42" stroke="#C9A96E" strokeWidth="1.2" fill="none"/>
            <circle cx="40" cy="22" r="8" stroke="#2B6B4A" strokeWidth="1.5" fill="none"/>
            <path d="M32,30 Q28,50 30,65 Q40,70 50,65 Q52,50 48,30" stroke="#2B6B4A" strokeWidth="1.5" fill="none"/>
            <circle cx="40" cy="54" r="5" stroke="#2B6B4A" strokeWidth="1.2" fill="none"/>
            <path d="M30,45 Q35,58 40,60 Q45,58 50,45" stroke="#2B6B4A" strokeWidth="1.2" fill="none"/>
            <path d="M8,50 Q12,44 10,38" stroke="#C9A96E" strokeWidth="1" fill="none"/>
            <path d="M8,50 Q4,44 6,38" stroke="#C9A96E" strokeWidth="1" fill="none"/>
            <path d="M72,50 Q68,44 70,38" stroke="#C9A96E" strokeWidth="1" fill="none"/>
            <path d="M72,50 Q76,44 74,38" stroke="#C9A96E" strokeWidth="1" fill="none"/>
          </svg>
        </div>

        <h1 className="lang-wordmark">UMMA</h1>

        <div className="lang-divider">
          <span className="lang-divider__line" />
          <span className="lang-divider__diamond">✦</span>
          <span className="lang-divider__line" />
        </div>

        <p className="lang-tagline">Your maternal and child health companion</p>

        <div className="lang-heart">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="#C9A96E">
            <path d="M12,21 C12,21 2,13 2,7 C2,4.2 4.2,2 7,2 C9,2 10.8,3.1 12,4.7 C13.2,3.1 15,2 17,2 C19.8,2 22,4.2 22,7 C22,13 12,21 12,21Z"/>
          </svg>
        </div>

        <p className="lang-tagline-ha">Abokiyar lafiyar uwa da yara</p>

        <p className="lang-choose">CHOOSE YOUR LANGUAGE</p>

        <div className="lang-buttons">
          <button className="lang-btn lang-btn--primary" onClick={() => onSelect('en')}>
            <svg className="lang-btn__svg" viewBox="0 0 24 24" fill="none" width="22" height="22">
              <circle cx="12" cy="12" r="10" stroke="#C9A96E" strokeWidth="1.5"/>
              <path d="M2,12 Q8,8 12,12 Q16,16 22,12" stroke="#C9A96E" strokeWidth="1.2" fill="none"/>
              <path d="M12,2 Q8,8 12,12 Q16,8 12,2" stroke="#C9A96E" strokeWidth="1.2" fill="none"/>
              <path d="M12,12 Q8,16 12,22 Q16,16 12,12" stroke="#C9A96E" strokeWidth="1.2" fill="none"/>
            </svg>
            <span>ENGLISH</span>
            <span className="lang-btn__arrow">›</span>
          </button>
          <button className="lang-btn lang-btn--secondary" onClick={() => onSelect('ha')}>
            <svg className="lang-btn__svg" viewBox="0 0 24 24" fill="none" width="22" height="22">
              <path d="M12,3 C12,3 8,6 8,10 C8,14 12,21 12,21 C12,21 16,14 16,10 C16,6 12,3 12,3Z" stroke="#C9A96E" strokeWidth="1.5" fill="none"/>
              <path d="M12,3 L12,21" stroke="#C9A96E" strokeWidth="1" opacity="0.6"/>
              <path d="M8,9 Q10,8 12,9 Q14,8 16,9" stroke="#C9A96E" strokeWidth="1" opacity="0.6"/>
              <path d="M8,13 Q10,12 12,13 Q14,12 16,13" stroke="#C9A96E" strokeWidth="1" opacity="0.6"/>
            </svg>
            <span>HAUSA</span>
            <span className="lang-btn__arrow">›</span>
          </button>
        </div>

        <div className="lang-footer">
          <span>TRUSTED · COMPASSIONATE · EVIDENCE-BASED</span>
          <span>BUILT FOR MOTHERS. BUILT FOR FAMILIES.</span>
        </div>

      </div>
    </div>
  );
}
