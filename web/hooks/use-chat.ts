'use client';
import {useEffect, useRef, useState} from 'react';
import {request, streamChat, ChatFailure} from '../lib/api';
import type {ChatMode, Me, RunAction} from '../lib/types';

export function useChat(companionId: string, me: Me, run: RunAction) {
  const [draft, setDraft] = useState('');
  const [warning, setWarning] = useState('');
  const [mode, setMode] = useState<ChatMode>('normal');
  const [streaming, setStreaming] = useState('');
  const [generating, setGenerating] = useState(false);
  const [choices, setChoices] = useState<string[]>([]);
  const pending = useRef<{content: string; mode: ChatMode; request_id: string} | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => {controller.current?.abort();}, []);
  const send = () => run(async () => {
    if (!draft.trim()) return;
    if (!pending.current || pending.current.content !== draft || pending.current.mode !== mode) {
      pending.current = {content: draft, mode, request_id: crypto.randomUUID()};
    }
    controller.current = new AbortController(); setGenerating(true); setStreaming(''); setWarning('');
    try {
      await streamChat(`/companions/${companionId}/messages`, me.csrf, pending.current,
        delta => setStreaming(text => text + delta), controller.current.signal, setWarning);
      pending.current = null; setDraft('');
    } catch (error) {
      if (controller.current?.signal.aborted) {
        throw new ChatFailure('Generation stopped. Your draft is preserved. Check your conversation and usage before retrying; the provider may have used tokens.', false);
      }
      if (error instanceof ChatFailure && error.safeToRetry) pending.current = null;
      throw error;
    } finally {setStreaming(''); setGenerating(false); controller.current = null;}
  });
  const suggest = () => run(async () => {
    const result = await request<{choices: string[]}>(`/companions/${companionId}/choices`, me.csrf, {request_id: crypto.randomUUID()});
    setChoices(result.choices);
  });
  const stop = () => controller.current?.abort();
  return {warning, draft, setDraft, mode, setMode, streaming, generating, stop, choices, send, suggest};
}
