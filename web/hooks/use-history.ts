'use client';
import {useCallback, useState} from 'react';
import {request} from '../lib/api';
import {queryCache} from '../lib/query-cache';
import type {Message} from '../lib/types';
import {useResource} from './use-resource';

export function useHistory(companionId: string) {
  const [pages, setPages] = useState(1);
  const fetcher = useCallback((key: string) => queryCache.read(key, async signal => {
    let messages: Message[] = []; let hasOlder = true;
    for (let page = 0; page < pages && hasOlder; page++) {
      const first = messages[0];
      const before = first ? `?before=${first.created}&before_id=${encodeURIComponent(first.id)}` : '';
      const batch = await request<Message[]>(`/companions/${companionId}/messages${before}`, '', undefined, 'GET', signal);
      messages = [...batch, ...messages]; hasOlder = batch.length === 50;
    }
    return {messages, hasOlder};
  }), [companionId, pages]);
  const result = useResource(`history:${companionId}:${pages}`, fetcher);
  // Keep the previous page visible while the larger history is loading.
  const [previous, setPrevious] = useState(result.data);
  if (result.data && result.data !== previous) setPrevious(result.data);
  return {...result, data: result.data ?? previous, loadOlder: () => setPages(count => count + 1)};
}
