'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {read, errorText} from '../lib/api';
import {CancelledRead, queryCache} from '../lib/query-cache';
import {useNetwork} from './use-network';

export function useResource<T>(path: string | null, fetcher: (path: string) => Promise<T> = read) {
  const [state, setState] = useState<{path: string | null; data?: T; error: string; loading: boolean}>({path, error: '', loading: !!path});
  const sequence = useRef(0);
  const online = useNetwork();
  const load = useCallback(async () => {
    const id = ++sequence.current;
    if (!path || !online) return;
    setState(previous => ({path, data: previous.path === path ? previous.data : queryCache.peek<T>(path), error: '', loading: true}));
    try {
      const data = await fetcher(path);
      if (id === sequence.current) setState({path, data, error: '', loading: false});
    } catch (error) {
      if (id === sequence.current && !(error instanceof CancelledRead)) {
        setState(previous => ({...previous, error: errorText(error), loading: false}));
      }
    }
  }, [path, online, fetcher]);
  useEffect(() => {
    void load();
    const unsubscribe = queryCache.subscribe(() => {void load();});
    return () => {sequence.current++; unsubscribe();};
  }, [load]);
  const data = state.path === path ? state.data : path ? queryCache.peek<T>(path) : undefined;
  return {data, error: state.path === path ? state.error : '', loading: online && !!path && (state.path !== path || state.loading), retry: load};
}
