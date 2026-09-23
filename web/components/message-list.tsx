'use client';
import {useLayoutEffect, useRef} from 'react';
import type {Companion, Message} from '../lib/types';
import {request} from '../lib/api';
import {useWorkspace} from './workspace-context';
import {ReadStatus} from './read-status';

type Props = {companion: Companion; messages: Message[]; hasOlder: boolean; streaming: string; loading: boolean; error: string; retry: () => Promise<unknown>; onOlder: () => void};
export function MessageList({companion, messages, hasOlder, streaming, loading, error, retry, onOlder}: Props) {
  const {me, actions: {disabled, busy, run}} = useWorkspace();
  const container = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const anchor = useRef<{height: number; top: number} | null>(null);
  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    if (anchor.current) {
      if (!loading) {element.scrollTop = anchor.current.top + element.scrollHeight - anchor.current.height; anchor.current = null;}
    } else if (stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [messages, streaming, loading]);
  return <div className="messages" ref={container} aria-label="Chat history" onScroll={() => {
    const element = container.current;
    if (element) stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
  }}>
    {hasOlder && <button className="text" disabled={disabled || loading} onClick={() => {
      if (container.current) anchor.current = {height: container.current.scrollHeight, top: container.current.scrollTop};
      stickToBottom.current = false; onOlder();
    }}>Load earlier messages</button>}
    <ReadStatus loading={loading} error={error} retry={retry} empty={!messages.length}/>
    {!loading && !error && messages.length === 0 && <div className="empty"><h3>How was your day?</h3><p>A little space where someone is ready to listen.</p></div>}
    {messages.map(message => <article key={message.id} className={`message ${message.role}`}>
      <small>{message.role === 'user' ? 'You' : companion.name} · {new Date(message.created * 1000).toLocaleTimeString('en', {hour: '2-digit', minute: '2-digit'})}</small><p dir="auto">{message.content}</p>
      <div className="message-actions">
        <button disabled={disabled} onClick={() => {
          if (window.confirm('Save this message as a long-term memory for this companion? Any sensitive information in it may also be used.')) void run(async () => {
            await request(`/companions/${companion.id}/memories`, me.csrf, {source_message_id: message.id, consent: true});
          });
        }}>Save as memory</button>
        <button disabled={disabled} onClick={() => {
          if (window.confirm('Archiving excludes this message from chat context and removes its associated memories. Continue?')) void run(async () => {
            await request(`/messages/${message.id}/archive`, me.csrf, {archived: true}, 'PATCH');
          });
        }}>Private archive</button>
        <button disabled={disabled} onClick={() => void run(async () => {await request(`/messages/${message.id}`, me.csrf, undefined, 'DELETE');})}>Delete</button>
      </div>
    </article>)}
    {streaming && <article className="message assistant"><small>Replying · Not yet confirmed as saved</small><p dir="auto">{streaming}</p></article>}
    {busy && <p role="status">Working on it…</p>}
  </div>;
}
