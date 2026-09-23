'use client';
import {useResource} from '../hooks/use-resource';
import type {Usage} from '../lib/types';
import {ReadStatus} from './read-status';

export function UsagePanel({onClose}: {onClose: () => void}) {
  const usage = useResource<Usage[]>('/usage');
  return <section className="card usage-panel"><h3>Usage and pending requests</h3><button className="text" onClick={onClose}>Close</button>
    <ReadStatus {...usage} empty={!usage.data}/>
    {usage.data?.map(item => <p key={item.id}><code>{item.id.slice(0, 8)}</code> · {item.purpose} · {item.status} · Used: {item.actual} / Reserved: {item.reserved}</p>)}
    {usage.data?.length === 0 && <p>No usage recorded yet.</p>}
    <small>Pending requests are not retried automatically. Contact the administrator if reserved usage needs review.</small>
  </section>;
}
