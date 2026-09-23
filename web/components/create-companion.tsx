'use client';
import {useState} from 'react';
import {request} from '../lib/api';
import type {CompanionInput} from '../lib/types';
import {useWorkspace} from './workspace-context';

export function CreateCompanion({onCreated, onCancel}: {onCreated: (id: string) => void; onCancel?: () => void}) {
  const {me, actions: {busy, disabled, run}} = useWorkspace();
  const [form, setForm] = useState<CompanionInput>({name: '', kind: 'human', profile: '', fictional: false});
  return <form className="card create" onSubmit={event => {event.preventDefault(); void run(async () => {
    const result = await request<{id: string}>('/companions', me.csrf, form); onCreated(result.id);
  });}}>
    <p className="eyebrow">SOMEONE NEW</p><h2>Who would you like to meet?</h2>
    <label>Name<input required maxLength={80} value={form.name} onChange={event => setForm({...form, name: event.target.value})} placeholder="Give your companion a name" /></label>
    <label htmlFor="companion-kind">Type</label><select id="companion-kind" value={form.kind} onChange={event => setForm({...form, kind: event.target.value === 'animal' ? 'animal' : 'human'})}>
      <option value="human">Fictional person</option><option value="animal">Animal</option>
    </select>
    <label>Background, personality, and appearance<textarea required maxLength={2000} value={form.profile} onChange={event => setForm({...form, profile: event.target.value})} placeholder="For example: a secondhand bookshop owner who loves rainy days, is kind, and has a mind of their own…" /></label>
    <label className="check"><input type="checkbox" required checked={form.fictional} onChange={event => setForm({...form, fictional: event.target.checked})} />This is an original fictional companion, not a real person or an existing character.</label>
    <p className="notice">{me.provider === 'mock' ? 'Demo mode is active. No real AI model is called.' : 'Your description will be reviewed and an original background generated in English. This uses model credits.'}</p>
    <button disabled={disabled}>{busy ? 'Creating…' : 'Let the story begin →'}</button>
    {onCancel && <button type="button" className="text" disabled={busy} onClick={onCancel}>Cancel</button>}
  </form>;
}
