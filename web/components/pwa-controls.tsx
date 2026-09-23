'use client';
import {useEffect, useState} from 'react';

type InstallPrompt = Event & {prompt: () => Promise<void>; userChoice: Promise<{outcome: 'accepted' | 'dismissed'}>};

export function PwaControls() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [installed, setInstalled] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [update, setUpdate] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const display = window.matchMedia('(display-mode: standalone)');
    const detect = () => setInstalled(display.matches || ('standalone' in navigator && navigator.standalone === true));
    detect(); display.addEventListener('change', detect);
    const available = (event: Event) => {event.preventDefault(); setPrompt(event as InstallPrompt);};
    const accepted = () => {setInstalled(true); setPrompt(null);};
    window.addEventListener('beforeinstallprompt', available);
    window.addEventListener('appinstalled', accepted);
    let stopped = false;
    let registration: ServiceWorkerRegistration | undefined;
    let worker: ServiceWorker | null = null;
    const stateChanged = () => {
      if (!stopped && worker?.state === 'installed' && navigator.serviceWorker.controller) setUpdate(true);
    };
    const updateFound = () => {
      worker?.removeEventListener('statechange', stateChanged);
      worker = registration?.installing ?? null;
      worker?.addEventListener('statechange', stateChanged);
    };
    if ('serviceWorker' in navigator && process.env.NODE_ENV === 'production') {
      void navigator.serviceWorker.register('/sw.js', {scope: '/', updateViaCache: 'none'}).then(result => {
        if (stopped) return;
        registration = result; setUpdate(!!result.waiting);
        result.addEventListener('updatefound', updateFound); updateFound();
      }).catch(() => {if (!stopped) setError('Offline pages are unavailable. You can still use Near online.');});
    }
    return () => {
      stopped = true; display.removeEventListener('change', detect);
      window.removeEventListener('beforeinstallprompt', available); window.removeEventListener('appinstalled', accepted);
      registration?.removeEventListener('updatefound', updateFound); worker?.removeEventListener('statechange', stateChanged);
    };
  }, []);
  return <div className="app-tools">
    {!installed && (prompt ? <button className="text" disabled={installing} onClick={() => {
      setInstalling(true);
      void prompt.prompt().then(() => prompt.userChoice).catch(() => setError('Use your browser menu to install Near.'))
        .finally(() => {setPrompt(null); setInstalling(false);});
    }}>Install Near</button> : <details><summary>Install app</summary><p>Choose “Install app” or “Add to Home Screen” in your browser menu. On iPhone or iPad, use the Safari share menu. Installation requires HTTPS or localhost and a supported browser.</p></details>)}
    {update && <small role="status">An update is ready. Close all Near windows and reopen to update.</small>}
    {error && <small role="status">{error}</small>}
  </div>;
}
