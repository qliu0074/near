'use client';
import {request} from '../lib/api';
import type {Companion} from '../lib/types';
import {useWorkspace} from './workspace-context';

type Props = {companions: Companion[]; selected: string; onSelect: (id: string) => void; onCreate: () => void; onUsage: () => void; onSignedOut: () => void};
export function Sidebar({companions, selected, onSelect, onCreate, onUsage, onSignedOut}: Props) {
  const {me, actions: {disabled, run}} = useWorkspace();
  const logout = (all: boolean) => run(async () => {
    await request(`/auth/logout${all ? '?all_devices=true' : ''}`, me.csrf, {}); onSignedOut();
  });
  return <aside className="sidebar"><div className="brand">near<span>Everyday moments, remembered.</span></div>
    <p className="eyebrow">MY COMPANIONS</p>
    {companions.map(companion => <button disabled={disabled} className={`companion ${companion.id === selected ? 'chosen' : ''}`} key={companion.id} onClick={() => onSelect(companion.id)}>
      <span className="avatar">{companion.kind === 'animal' ? '🐾' : '✦'}</span><span>{companion.name}<small>{companion.kind === 'animal' ? 'Animal companion' : 'Fictional person'}</small></span>
    </button>)}
    <button className="secondary" disabled={disabled} onClick={onCreate}>＋ Create companion</button>
    <div className="account"><span>{me.email}</span><small>Available: {me.available.toLocaleString('en')} tokens</small>
      <small>Used: {me.used.toLocaleString('en')} · Reserved: {me.reserved.toLocaleString('en')}</small>
      <button className="text" onClick={onUsage}>Usage</button>
      <button className="text" disabled={disabled} onClick={() => void run(async () => {
        const data = await request<unknown>('/account/export');
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
        const link = document.createElement('a'); link.href = url; link.download = 'near-data.json';
        document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      })}>Export my data</button>
      <button className="text danger" disabled={disabled} onClick={() => {
        const confirmEmail = window.prompt('Delete your account and all chats, archives, and memories. Enter your email to confirm:');
        if (confirmEmail) void run(async () => {await request('/account', me.csrf, {confirm_email: confirmEmail}, 'DELETE'); onSignedOut();});
      }}>Delete account</button>
      <button className="text" disabled={disabled} onClick={() => void logout(false)}>Sign out</button>
      <button className="text" disabled={disabled} onClick={() => void logout(true)}>Sign out all devices</button>
    </div>
  </aside>;
}
