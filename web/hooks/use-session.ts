'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {ApiError, errorText, read} from '../lib/api';
import {CancelledRead, queryCache} from '../lib/query-cache';
import type {Me} from '../lib/types';

export function useSession() {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const current = useRef<Me | null>(null);
  const reset = useCallback(() => {
    sequence.current++; current.current = null; setMe(null); setReady(true); setError('');
    queryCache.invalidate();
  }, []);
  const refresh = useCallback(async () => {
    const id = ++sequence.current;
    setError('');
    try {
      const user = await read<Me>('/me');
      if (id === sequence.current) {current.current = user; setMe(user);}
    } catch (error) {
      if (id !== sequence.current || error instanceof CancelledRead) return;
      if (error instanceof ApiError && error.status === 401) setMe(null);
      else {setError(errorText(error)); throw error;}
    } finally {if (id === sequence.current) setReady(true);}
  }, []);
  useEffect(() => {
    void refresh().catch(() => undefined);
    const unauthorized = () => {if (current.current) reset();};
    window.addEventListener('near:unauthorized', unauthorized);
    const reconnect = () => {queryCache.invalidate(); void refresh().catch(() => undefined);};
    window.addEventListener('online', reconnect);
    return () => {sequence.current++; window.removeEventListener('near:unauthorized', unauthorized); window.removeEventListener('online', reconnect);};
  }, [refresh, reset]);
  return {me, ready, error, refresh, reset};
}
