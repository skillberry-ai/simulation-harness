import React from 'react';
import { createRoot } from 'react-dom/client';
import './theme.css';
import { App } from './App';
import { setHarnessUrlGetter } from './api/http';
import { useConnectionStore } from './state/useConnectionStore';

setHarnessUrlGetter(() => useConnectionStore.getState().harnessUrl);

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
