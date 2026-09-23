'use client';
import {useEffect, useRef, useState} from 'react';
import {queryCache} from '../lib/query-cache';
import type {SyncEvents} from '../lib/types';
import {useNetwork} from './use-network';

export function useLiveSync(onRevoked: () => void) {
  const online = useNetwork();
  const [status, setStatus] = useState('Connecting');
  const cursor = useRef(0);
  useEffect(() => {
    if (!online) return;
    let stopped = false;
    const source = new EventSource(`/v1/sync/stream?after=${cursor.current}`);
    source.addEventListener('revoked', () => {if (!stopped) {source.close(); onRevoked();}});
    source.onopen = () => {if (!stopped) {setStatus('Live sync connected'); queryCache.invalidate();}};
    source.onerror = () => {
      if (!stopped) {setStatus('Connection lost · Reconnecting'); queryCache.invalidate();}
    };
    source.onmessage = event => {
      if (stopped) return;
      try {
        const result: SyncEvents = JSON.parse(event.data);
        if (!Array.isArray(result.events) || !Number.isFinite(result.cursor)) return;
        if (result.events.length) queryCache.invalidate();
        cursor.current = result.cursor;
        setStatus('Live sync connected');
      } catch {setStatus('Sync interrupted · Waiting to reconnect');}
    };
    const focus = () => {if (document.visibilityState === 'visible') queryCache.invalidate();};
    document.addEventListener('visibilitychange', focus);
    return () => {stopped = true; source.close(); document.removeEventListener('visibilitychange', focus);};
  }, [online, onRevoked]);
  return online ? status : 'Offline';
}
