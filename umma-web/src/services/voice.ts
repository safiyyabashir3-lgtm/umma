import * as SpeechSDK from 'microsoft-cognitiveservices-speech-sdk';

const SPEECH_KEY = import.meta.env.VITE_SPEECH_KEY;
const SPEECH_REGION = import.meta.env.VITE_SPEECH_REGION;

function getSpeechConfig(language: string) {
  const config = SpeechSDK.SpeechConfig.fromSubscription(SPEECH_KEY, SPEECH_REGION);
  config.speechRecognitionLanguage = language === 'ha' ? 'ha-NG' : 'en-NG';
  config.speechSynthesisLanguage = language === 'ha' ? 'ha-NG' : 'en-NG';
  config.speechSynthesisVoiceName = language === 'ha'
    ? 'ha-NG-HadijaNeural'
    : 'en-NG-EzinneNeural';
  return config;
}

export function startListening(
  language: string,
  onResult: (text: string) => void,
  onError: () => void
): SpeechSDK.SpeechRecognizer {
  const config = getSpeechConfig(language);
  const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
  const recognizer = new SpeechSDK.SpeechRecognizer(config, audioConfig);

  recognizer.recognizeOnceAsync(
    result => {
      if (result.reason === SpeechSDK.ResultReason.RecognizedSpeech && result.text) {
        onResult(result.text);
      } else {
        onError();
      }
      recognizer.close();
    },
    () => {
      onError();
      recognizer.close();
    }
  );

  return recognizer;
}

export async function speak(text: string, language: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const config = getSpeechConfig(language);
    const audioConfig = SpeechSDK.AudioConfig.fromDefaultSpeakerOutput();
    const synthesizer = new SpeechSDK.SpeechSynthesizer(config, audioConfig);

    synthesizer.speakTextAsync(
      text,
      () => {
        synthesizer.close();
        resolve();
      },
      error => {
        synthesizer.close();
        reject(error);
      }
    );
  });
}
