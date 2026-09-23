'use client';
import {useSession} from '../hooks/use-session';
import {useNetwork} from '../hooks/use-network';
import {LoginForm} from './login-form';
import {Workspace} from './workspace';
import {PwaControls} from './pwa-controls';

export function NearApp() {
  const session = useSession();
  const online = useNetwork();
  return <>
    <PwaControls/>
    {!online && <div className="connection-banner" role="status">You are offline. Your draft stays on this page. Send it manually when you reconnect.</div>}
    {session.me && session.error && <p className="error" role="alert">{session.error}</p>}
    {!session.ready ? <main className="loading" role="status">NEAR / Restoring your session…</main>
      : session.error && !session.me ? <main className="loading"><h1>Unable to connect to Near</h1><p role="alert">{session.error}</p>
        <button disabled={!online} onClick={() => void session.refresh().catch(() => undefined)}>Reconnect</button></main>
      : session.me ? <Workspace key={session.me.email} user={session.me} onSignedOut={session.reset}/>
      : <LoginForm onSignedIn={session.refresh}/>}
  </>;
}
