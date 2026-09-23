'use client';
import {useState} from 'react';
import type {Companion, Me} from '../lib/types';
import {useActions} from '../hooks/use-actions';
import {useResource} from '../hooks/use-resource';
import {useLiveSync} from '../hooks/use-live-sync';
import {WorkspaceContext} from './workspace-context';
import {Sidebar} from './sidebar';
import {CreateCompanion} from './create-companion';
import {CompanionPanel} from './companion-panel';
import {ChatPanel} from './chat-panel';
import {UsagePanel} from './usage-panel';
import {ReadStatus} from './read-status';

export function Workspace({user, onSignedOut}: {user: Me; onSignedOut: () => void}) {
  const actions = useActions();
  const me = useResource<Me>('/me');
  const companions = useResource<Companion[]>('/companions');
  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const sync = useLiveSync(onSignedOut);
  const items = companions.data ?? [];
  const active = items.find(item => item.id === selected);
  const select = (id: string) => {setSelected(id); setCreating(false); actions.clearError();};
  return <WorkspaceContext.Provider value={{me: me.data ?? user, actions}}>
    <main className="shell">
      <Sidebar companions={items} selected={selected} onSelect={select} onCreate={() => setCreating(true)} onUsage={() => setUsageOpen(open => !open)} onSignedOut={onSignedOut}/>
      <section className="workspace">
        <header><div><p className="eyebrow">A SPACE TO BE YOURSELF</p><h2>{active?.name ?? 'Your companion space'}</h2></div><span className="status" role="status">● {sync}</span></header>
        {actions.error && <p className="error" role="alert">{actions.error}</p>}
        <ReadStatus {...companions} empty={!companions.data}/>
        {me.error && <ReadStatus {...me}/>}
        {usageOpen && <UsagePanel onClose={() => setUsageOpen(false)}/>}
        {creating || (companions.data && !items.length) ? <CreateCompanion onCreated={select} onCancel={items.length ? () => setCreating(false) : undefined}/>
          : active ? <div className="conversation" key={active.id}>
            <CompanionPanel companion={active} onDeleted={() => setSelected('')}/><ChatPanel companion={active}/>
          </div> : !companions.loading && <div className="empty"><div className="orb">✦</div><h2>Choose a companion to start a conversation.</h2><p>No need to find the perfect words. A simple hello is enough.</p></div>}
      </section>
    </main>
  </WorkspaceContext.Provider>;
}
