import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';
import { bootstrapThemeFromStorage } from './theme/default';
import { bootstrapAppLanguageFromStorage } from './i18n/language';

bootstrapThemeFromStorage();
bootstrapAppLanguageFromStorage();

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
