import React from 'react';
import { createRoot } from 'react-dom/client';
import { initializeDesktop } from './desktop';
import './styles.css';
const root = document.getElementById('root')!;
initializeDesktop()
  .then(() => import('./App'))
  .then(({ App }) => createRoot(root).render(<React.StrictMode><App /></React.StrictMode>))
  .catch((error: unknown) => {
    const message = document.createElement('p');
    message.setAttribute('role', 'alert');
    message.textContent = `Studio could not start: ${error instanceof Error ? error.message : String(error)}`;
    root.replaceChildren(message);
  });
