export class CancelledRead extends Error {
  constructor() {super('Read invalidated');}
}

/** Per-tab memory only. Invalidation also prevents late responses restoring old data. */
export class QueryCache {
  private entries = new Map<string, {value: unknown; expires: number}>();
  private pending = new Map<string, {controller: AbortController; promise: Promise<unknown>}>();
  private listeners = new Set<() => void>();
  private generation = 0;

  constructor(private ttl = 15_000, private capacity = 100) {}

  peek<T>(key: string): T | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (entry.expires <= Date.now()) {this.entries.delete(key); return undefined;}
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value as T;
  }

  read<T>(key: string, loader: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const cached = this.peek<T>(key);
    if (cached !== undefined) return Promise.resolve(cached);
    const existing = this.pending.get(key);
    if (existing) return existing.promise as Promise<T>;
    const generation = this.generation;
    const controller = new AbortController();
    const promise = Promise.resolve().then(() => loader(controller.signal)).then(value => {
      if (generation !== this.generation) throw new CancelledRead();
      this.entries.set(key, {value, expires: Date.now() + this.ttl});
      while (this.entries.size > this.capacity) this.entries.delete(this.entries.keys().next().value!);
      return value;
    }).catch((error: unknown) => {
      if (generation !== this.generation) throw new CancelledRead();
      throw error;
    }).finally(() => {
      if (this.pending.get(key)?.controller === controller) this.pending.delete(key);
    });
    this.pending.set(key, {controller, promise});
    return promise;
  }

  invalidate = () => {
    this.generation++;
    this.entries.clear();
    for (const request of this.pending.values()) request.controller.abort();
    this.pending.clear();
    for (const listener of this.listeners) listener();
  };

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {this.listeners.delete(listener);};
  };
}

export const queryCache = new QueryCache();
