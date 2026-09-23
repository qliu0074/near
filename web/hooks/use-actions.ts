'use client';
import {useCallback, useRef, useState} from 'react';
import {errorText} from '../lib/api';
import {CancelledRead} from '../lib/query-cache';
import {useNetwork} from './use-network';
import type {RunAction} from '../lib/types';

export function useActions() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const online = useNetwork();
  const run: RunAction = useCallback(async task => {
    if (lock.current) return false;
    if (!navigator.onLine) {setError('You are offline. Reconnect before continuing.'); return false;}
    lock.current = true; setBusy(true); setError('');
    try {await task(); return true;}
    catch (error) {if (!(error instanceof CancelledRead)) setError(errorText(error)); return false;}
    finally {lock.current = false; setBusy(false);}
  }, []);
  return {busy, disabled: busy || !online, error, run, clearError: () => setError('')};
}
