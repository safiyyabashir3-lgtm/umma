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

  const handleLanguageToggle = () => {
    const next: Language = language === 'en' ? 'ha' : 'en';
    localStorage.setItem('umma_language', next);
    setLanguage(next);
  };

  if (!language) {
    return <LanguageScreen onSelect={handleLanguageSelect} />;
  }

  return <ChatScreen language={language} onLanguageToggle={handleLanguageToggle} />;
}

export default App;
