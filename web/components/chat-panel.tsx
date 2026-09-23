'use client';
import type {Companion} from '../lib/types';
import {useChat} from '../hooks/use-chat';
import {useHistory} from '../hooks/use-history';
import {useWorkspace} from './workspace-context';
import {MessageList} from './message-list';

export function ChatPanel({companion}: {companion: Companion}) {
  const {me, actions: {busy, disabled, run}} = useWorkspace();
  const history = useHistory(companion.id);
  const chat = useChat(companion.id, me, run);
  return <section className="chat" aria-label="Conversation">
    <div className="chat-note">{me.provider === 'mock' ? 'Demo chat' : 'Qwen chat'} · Chats are kept for 3 days · Memories are saved only with your consent</div>
    {chat.warning && <p role="status">{chat.warning}</p>}
    <MessageList companion={companion} messages={history.data?.messages ?? []} hasOlder={history.data?.hasOlder ?? false}
      loading={history.loading} error={history.error} retry={history.retry} onOlder={history.loadOlder} streaming={chat.streaming}/>
    <div className="choice-bar"><div><label htmlFor="chat-mode">Chat mode</label><select id="chat-mode" disabled={disabled} value={chat.mode} onChange={event => chat.setMode(event.target.value === 'fast' ? 'fast' : 'normal')}>
      <option value="normal">Standard · Memory search</option><option value="fast">Fast · Recent chat only</option>
    </select></div>
      <button className="text" disabled={disabled} onClick={() => void chat.suggest()}>Suggest three topics</button>
      {chat.choices.map(choice => <button className="secondary" disabled={busy} key={choice} onClick={() => chat.setDraft(choice)}>{choice}</button>)}
    </div>
    <form className="composer" onSubmit={event => {event.preventDefault(); void chat.send();}}>
      <label className="sr-only" htmlFor="message">Message</label><textarea id="message" dir="auto" disabled={busy} maxLength={2000} value={chat.draft} onChange={event => chat.setDraft(event.target.value)} placeholder="Share a little about your day…"/>
      <button disabled={disabled || !chat.draft.trim()}>Send ↑</button>
      <small>{chat.draft.length}/2000 · AI companionship does not replace real relationships or professional support</small>
    </form>
  </section>;
}
