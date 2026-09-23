export type Me = {email: string; csrf: string; used: number; reserved: number; available: number; provider: string; portraits_enabled: boolean};
export type Companion = {id: string; name: string; kind: 'human' | 'animal'; profile: string; portrait_count: number; version: number};
export type CompanionInput = Pick<Companion, 'name' | 'kind' | 'profile'> & {fictional: boolean};
export type Usage = {id: string; purpose: string; status: string; reserved: number; actual: number};
export type Message = {id: string; role: string; content: string; created: number};
export type Memory = {id: string; content: string; source: string};
export type SyncEvents = {events: {id: number; kind: string; entity: string}[]; cursor: number; has_more: boolean};
export type ChatMode = 'fast' | 'normal';
export type RunAction = (task: () => Promise<void>) => Promise<boolean>;
