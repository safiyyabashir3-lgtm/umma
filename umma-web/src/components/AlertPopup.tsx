import { useState } from 'react';
import { sendAlert } from '../services/api';
import { DebugInfo, Language } from '../types';
import './AlertPopup.css';

interface Props {
  actionTier: string;
  debugInfo: DebugInfo;
  sessionId: string;
  userId: string;
  language: Language;
  onDismiss: () => void;
}

function resolveAlert(actionTier: string, debugInfo: DebugInfo) {
  const isPregnancy = debugInfo.reported_symptoms?.some(s =>
    ['pregnant', 'pregnancy', 'trimester', 'baby', 'labour', 'bleeding'].some(k =>
      s.toLowerCase().includes(k)
    )
  );

  switch (actionTier) {
    case 'emergency':
      return {
        alertType: 'emergency' as const,
        workerRole: undefined,
        heading: { en: 'Alert the emergency team?', ha: 'Sanar da ƙungiyar gaggawa?' },
        body: {
          en: 'We can notify the emergency doctors at AKTH so they are ready when you arrive.',
          ha: 'Zamu iya sanar da likitocin gaggawa a AKTH don su kasance a shirye lokacin da kuka zo.'
        },
        yesLabel: { en: 'Yes, notify them', ha: 'Ee, sanar da su' },
        icon: '🚨',
        confirmation: {
          en: (ref: string) => `Your UMMA reference number is *${ref}*.\n\nThe emergency team at AKTH has been notified. Please go to AKTH immediately and give this number to the doctors on arrival.`,
          ha: (ref: string) => `Lambar UMMA naku ita ce *${ref}*.\n\nAn sanar da ƙungiyar gaggawa a AKTH. Don Allah je AKTH yanzu kuma ku ba likitoci wannan lambar lokacin da kuka iso.`
        }
      };
    case 'urgent_clinic':
      return {
        alertType: 'urgent_clinic' as const,
        workerRole: undefined,
        heading: { en: 'Notify AKTH records desk?', ha: 'Sanar da ofishin rikodin AKTH?' },
        body: {
          en: 'We can let the AKTH records office know to expect you today or tomorrow.',
          ha: 'Zamu iya sanar da ofishin rikodin AKTH don su san za ku zo yau ko gobe.'
        },
        yesLabel: { en: 'Yes, let them know', ha: 'Ee, sanar da su' },
        icon: '📋',
        confirmation: {
          en: (ref: string) => `Your UMMA reference number is *${ref}*.\n\nThe AKTH records desk has been notified. When you arrive, give this number to the records officer so they can find your details quickly.`,
          ha: (ref: string) => `Lambar UMMA naku ita ce *${ref}*.\n\nAn sanar da ofishin rikodin AKTH. Lokacin da kuka iso, ku ba ma'aikacin rikodin wannan lambar don su samu bayanankku da sauri.`
        }
      };
    case 'home_care':
      return {
        alertType: 'chw' as const,
        workerRole: 'chew' as const,
        heading: { en: 'Would you like a health worker to follow up?', ha: 'Kuna so ma\'aikaciyar lafiya ta biyo ku?' },
        body: {
          en: 'A Community Health Worker can check in with you to make sure you are managing well at home.',
          ha: 'Ma\'aikaciyar lafiya za ta iya tuntuɓar ku don tabbatar cewa kuna lafiya a gida.'
        },
        yesLabel: { en: 'Yes, please', ha: 'Ee, don Allah' },
        icon: '👋',
        confirmation: {
          en: (ref: string) => `Your UMMA reference number is *${ref}*.\n\nA Community Health Worker has been notified and will contact you to check in. They may ask for this number when they reach out.`,
          ha: (ref: string) => `Lambar UMMA naku ita ce *${ref}*.\n\nAn sanar da ma'aikaciyar lafiya kuma za ta tuntuɓe ku. Tana iya tambayar wannan lambar lokacin da ta tuntube ku.`
        }
      };
    case 'monitor':
      return {
        alertType: 'chw' as const,
        workerRole: 'nurse' as const,
        heading: { en: 'Would you like a nurse to check in?', ha: 'Kuna so jinya ta tuntuɓe ku?' },
        body: {
          en: 'A nurse can follow up with you if your symptoms change or you need guidance.',
          ha: 'Jinya za ta iya biyo ku idan alamun sun canza ko kuna buƙatar jagora.'
        },
        yesLabel: { en: 'Yes, please', ha: 'Ee, don Allah' },
        icon: '👋',
        confirmation: {
          en: (ref: string) => `Your UMMA reference number is *${ref}*.\n\nA nurse has been notified and will contact you to check in. They may ask for this number when they reach out.`,
          ha: (ref: string) => `Lambar UMMA naku ita ce *${ref}*.\n\nAn sanar da jinya kuma za ta tuntuɓe ku. Tana iya tambayar wannan lambar lokacin da ta tuntube ku.`
        }
      };
    case 'uncertain':
      return {
        alertType: 'chw' as const,
        workerRole: (isPregnancy ? 'midwife' : 'nurse') as 'midwife' | 'nurse',
        heading: {
          en: isPregnancy ? 'Would you like a midwife to follow up?' : 'Would you like a health worker to follow up?',
          ha: isPregnancy ? 'Kuna so ungozoma ta biyo ku?' : 'Kuna so ma\'aikaciyar lafiya ta biyo ku?'
        },
        body: {
          en: isPregnancy
            ? 'A midwife can follow up with you for more guidance about your pregnancy.'
            : 'A health worker can follow up with you to help you understand what to do next.',
          ha: isPregnancy
            ? 'Ungozoma za ta iya biyo ku don ƙarin jagora game da cikinka.'
            : 'Ma\'aikaciyar lafiya za ta iya biyo ku don taimaka muku sanin abin da za ku yi gaba.'
        },
        yesLabel: { en: 'Yes, please', ha: 'Ee, don Allah' },
        icon: '👋',
        confirmation: {
          en: (ref: string) => `Your UMMA reference number is *${ref}*.\n\n${isPregnancy ? 'A midwife' : 'A health worker'} has been notified and will contact you. They may ask for this number when they reach out.`,
          ha: (ref: string) => `Lambar UMMA naku ita ce *${ref}*.\n\n${isPregnancy ? 'Ungozoma' : 'Ma\'aikaciyar lafiya'} an sanar da ita kuma za ta tuntuɓe ku. Tana iya tambayar wannan lambar lokacin da ta tuntube ku.`
        }
      };
    default:
      return null;
  }
}

export default function AlertPopup({ actionTier, debugInfo, sessionId, userId, language, onDismiss }: Props) {
  const [step, setStep] = useState<'prompt' | 'form' | 'sent' | 'failed'>('prompt');
  const [patientName, setPatientName] = useState('');
  const [patientAge, setPatientAge] = useState('');
  const [sending, setSending] = useState(false);
  const [ummaRef, setUmmaRef] = useState<string | null>(null);

  const config = resolveAlert(actionTier, debugInfo);
  if (!config) return null;

  const t = (obj: { en: string; ha: string }) => obj[language] ?? obj.en;

  const handleYes = () => setStep('form');

  const handleSend = async () => {
    setSending(true);
    try {
      const result = await sendAlert({
        alert_type: config.alertType,
        session_id: sessionId,
        user_id: userId,
        action_tier: actionTier,
        reported_symptoms: debugInfo.reported_symptoms || [],
        internal_diagnosis: debugInfo.internal_diagnosis || null,
        active_differentials: debugInfo.active_differentials || [],
        language,
        worker_role: config.workerRole,
        patient_name: patientName.trim() || undefined,
        patient_age: patientAge.trim() || undefined
      });
      if (result.success && result.umma_ref) {
        setUmmaRef(result.umma_ref);
        setStep('sent');
      } else {
        setStep('failed');
      }
    } catch {
      setStep('failed');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="alert-popup-overlay">
      <div className="alert-popup">

        {step === 'prompt' && (
          <>
            <div className="alert-popup__icon">{config.icon}</div>
            <h3 className="alert-popup__heading">{t(config.heading)}</h3>
            <p className="alert-popup__body">{t(config.body)}</p>
            <div className="alert-popup__actions">
              <button className="alert-popup__btn alert-popup__btn--yes" onClick={handleYes}>
                {t(config.yesLabel)}
              </button>
              <button className="alert-popup__btn alert-popup__btn--no" onClick={onDismiss}>
                {language === 'en' ? 'No, thank you' : 'A\'a, na gode'}
              </button>
            </div>
          </>
        )}

        {step === 'form' && (
          <>
            <div className="alert-popup__icon">{config.icon}</div>
            <h3 className="alert-popup__heading">
              {language === 'en' ? 'Your details' : 'Bayanankku'}
            </h3>
            <p className="alert-popup__body">
              {language === 'en'
                ? 'Please enter your name and age so the health team can identify you.'
                : 'Don Allah shigar da sunankku da shekaru don ƙungiyar lafiya ta gane ku.'}
            </p>
            <div className="alert-popup__form">
              <input
                className="alert-popup__input"
                type="text"
                placeholder={language === 'en' ? 'Your name' : 'Sunankku'}
                value={patientName}
                onChange={e => setPatientName(e.target.value)}
              />
              <input
                className="alert-popup__input"
                type="number"
                placeholder={language === 'en' ? 'Your age' : 'Shekarun ku'}
                value={patientAge}
                onChange={e => setPatientAge(e.target.value)}
              />
            </div>
            <div className="alert-popup__actions">
              <button
                className="alert-popup__btn alert-popup__btn--yes"
                onClick={handleSend}
                disabled={sending || !patientName.trim()}
              >
                {sending
                  ? (language === 'en' ? 'Sending...' : 'Aika...')
                  : (language === 'en' ? 'Send alert' : 'Aika saƙo')}
              </button>
              <button className="alert-popup__btn alert-popup__btn--no" onClick={() => setStep('prompt')} disabled={sending}>
                {language === 'en' ? 'Back' : 'Koma baya'}
              </button>
            </div>
          </>
        )}

        {step === 'sent' && ummaRef && (
          <div className="alert-popup__confirmation">
            <div className="alert-popup__check">✓</div>
            <div className="alert-popup__ref">{ummaRef}</div>
            <p className="alert-popup__ref-msg">
              {config.confirmation[language]?.(ummaRef) ?? config.confirmation.en(ummaRef)}
            </p>
            <button className="alert-popup__btn alert-popup__btn--close" onClick={onDismiss}>
              {language === 'en' ? 'Close' : 'Rufe'}
            </button>
          </div>
        )}

        {step === 'failed' && (
          <div className="alert-popup__confirmation alert-popup__confirmation--failed">
            <div className="alert-popup__check">⚠</div>
            <p>
              {language === 'en'
                ? 'Could not send. Please try again or go directly.'
                : 'Ba a iya aika ba. Don Allah sake gwadawa ko je kai tsaye.'}
            </p>
            <button className="alert-popup__btn alert-popup__btn--close" onClick={onDismiss}>
              {language === 'en' ? 'Close' : 'Rufe'}
            </button>
          </div>
        )}

      </div>
    </div>
  );
}
