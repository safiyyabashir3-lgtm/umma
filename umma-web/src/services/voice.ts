import * as SpeechSDK from 'microsoft-cognitiveservices-speech-sdk';

const SPEECH_KEY = import.meta.env.VITE_SPEECH_KEY;
const SPEECH_REGION = import.meta.env.VITE_SPEECH_REGION;

let currentPlayer: SpeechSDK.SpeakerAudioDestination | null = null;
let currentSynthesizer: SpeechSDK.SpeechSynthesizer | null = null;

function getSTTConfig() {
  const config = SpeechSDK.SpeechConfig.fromSubscription(SPEECH_KEY, SPEECH_REGION);
  config.speechRecognitionLanguage = 'en-NG';
  return config;
}

function getTTSConfig() {
  const config = SpeechSDK.SpeechConfig.fromSubscription(SPEECH_KEY, SPEECH_REGION);
  config.speechSynthesisLanguage = 'en-NG';
  config.speechSynthesisVoiceName = 'en-NG-EzinneNeural';
  return config;
}

export function startListening(
  onResult: (text: string) => void,
  onError: (reason: string) => void
): SpeechSDK.SpeechRecognizer {
  const config = getSTTConfig();
  const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
  const recognizer = new SpeechSDK.SpeechRecognizer(config, audioConfig);

  recognizer.recognizeOnceAsync(
    result => {
      if (result.reason === SpeechSDK.ResultReason.RecognizedSpeech && result.text) {
        onResult(result.text);
      } else {
        onError(result.errorDetails || 'No speech recognized');
      }
      recognizer.close();
    },
    error => {
      onError(String(error));
      recognizer.close();
    }
  );

  return recognizer;
}

export function stopSpeaking(): void {
  try { currentPlayer?.pause(); } catch {}
  try { currentSynthesizer?.close(); } catch {}
  currentPlayer = null;
  currentSynthesizer = null;
}

export async function speak(text: string): Promise<void> {
  stopSpeaking();
  return new Promise((resolve) => {
    const config = getTTSConfig();
    const player = new SpeechSDK.SpeakerAudioDestination();
    const audioConfig = SpeechSDK.AudioConfig.fromSpeakerOutput(player);
    const synthesizer = new SpeechSDK.SpeechSynthesizer(config, audioConfig);

    currentPlayer = player;
    currentSynthesizer = synthesizer;

    player.onAudioEnd = () => {
      synthesizer.close();
      currentPlayer = null;
      currentSynthesizer = null;
      resolve();
    };

    synthesizer.speakTextAsync(
      text,
      () => {},
      () => {
        synthesizer.close();
        currentPlayer = null;
        currentSynthesizer = null;
        resolve();
      }
    );
  });
}
