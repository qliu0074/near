'use client';
import {useState} from 'react';
import {useResource} from '../hooks/use-resource';
import {request} from '../lib/api';
import type {Companion, Memory, Message} from '../lib/types';
import {ReadStatus} from './read-status';
import {useWorkspace} from './workspace-context';

export function CompanionPanel({companion, onDeleted}: {companion: Companion; onDeleted: () => void}) {
  const {me, actions: {disabled, run}} = useWorkspace();
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const memories = useResource<Memory[]>(`/companions/${companion.id}/memories`);
  const archive = useResource<Message[]>(archiveOpen ? `/companions/${companion.id}/archive` : null);
  return <section className="portrait card" aria-label="Companion and memory settings">
    <span className="portrait-symbol">{companion.kind === 'animal' ? '🐾' : '✦'}</span>
    <small>Portrait placeholder · Not AI-generated</small><h2>{companion.name}</h2><p>{companion.profile}</p>
    <button className="secondary" disabled>Portraits unavailable · No charge</button>
    <button className="text" disabled={disabled} onClick={() => {
      const profile = window.prompt('Edit the companion profile:', companion.profile);
      if (profile) void run(async () => {await request(`/companions/${companion.id}`, me.csrf,
        {name: companion.name, profile, version: companion.version, fictional: true}, 'PATCH');});
    }}>Edit profile</button>
    <button className="text danger" disabled={disabled} onClick={() => {
      if (window.confirm('Delete this companion and all associated chats, archives, and memories?')) void run(async () => {
        await request(`/companions/${companion.id}`, me.csrf, undefined, 'DELETE'); onDeleted();
      });
    }}>Delete companion</button>
    <button className="text" aria-expanded={archiveOpen} onClick={() => setArchiveOpen(open => !open)}>Private archive</button>
    {archiveOpen && <div className="memories"><small>Archived messages are not included in chat context.</small><ReadStatus {...archive} empty={!archive.data}/>
      {archive.data?.length === 0 && <p>No archived messages yet.</p>}
      {archive.data?.map(message => <article key={message.id}><p dir="auto">{message.content}</p>
        <button className="text" disabled={disabled} onClick={() => void run(async () => {
          await request(`/messages/${message.id}/archive`, me.csrf, {archived: false}, 'PATCH');
        })}>Restore to chat</button>
        <button className="text" disabled={disabled} onClick={() => void run(async () => {
          await request(`/messages/${message.id}`, me.csrf, undefined, 'DELETE');
        })}>Delete archived message</button>
      </article>)}
    </div>}
    <button className="text" aria-expanded={memoryOpen} onClick={() => setMemoryOpen(open => !open)}>Memories · {memories.data?.length ?? '…'}</button>
    {memoryOpen && <div className="memories"><ReadStatus {...memories} empty={!memories.data}/>
      {memories.data?.length === 0 && <p>No memories saved yet.</p>}
      {memories.data?.map(memory => <article key={memory.id}><p dir="auto">{memory.content}</p>
        <button className="text" disabled={disabled} onClick={() => void run(async () => {
          await request(`/memories/${memory.id}`, me.csrf, undefined, 'DELETE');
        })}>Delete memory</button>
      </article>)}
    </div>}
  </section>;
}
