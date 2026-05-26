import { useState } from 'react';
import { Language } from './types';
import LanguageScreen from './screens/LanguageScreen';
import ChatScreen from './screens/ChatScreen';

function App() {
  const [language, setLanguage] = useState<Language | null>(() => {
    return (localStorage.getItem('umma_language') as Language) || null;
  });

  const handleLanguageSelect = (lang: Language) => {
    localStorage.setItem('umma_language', lang);
    setLanguage(lang);
  };

  if (!language) {
    return <LanguageScreen onSelect={handleLanguageSelect} />;
  }

  return <ChatScreen language={language} />;
}

export default App;
