'use client';
import {useState} from 'react';
import {request} from '../lib/api';
import {useActions} from '../hooks/use-actions';

export function LoginForm({onSignedIn}: {onSignedIn: () => Promise<void>}) {
  const [email, setEmail] = useState(''); const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState(''); const [mailSent, setMailSent] = useState(false);
  const {busy, disabled, error, run} = useActions();
  return <main className="landing">
    <div className="brand">near<span>Here for you, at your pace.</span></div>
    <section className="welcome"><p className="eyebrow">A LITTLE CLOSER, EVERY DAY</p>
      <h1>Even an ordinary day<br/>deserves to be heard.</h1><p>Create a fictional companion of your own.<br/>Remember what you choose to share and keep the little moments.</p>
      <div className="orb">✦</div></section>
    <form className="login card" onSubmit={event => {event.preventDefault(); void run(async () => {
      await request('/auth/email/verify', '', {email, code}); await onSignedIn();
    });}}>
      <p className="eyebrow">YOUR PRIVATE CORNER</p><h2>Welcome to Near</h2><p>Start your story with an email address.</p>
      <label>Email<input type="email" required autoComplete="email" disabled={busy} value={email} onChange={event => {
        setEmail(event.target.value); setDevCode(''); setMailSent(false); setCode('');
      }} placeholder="you@example.com" /></label>
      <button type="button" disabled={disabled || !email} className="secondary" onClick={() => void run(async () => {
        const result = await request<{development_code?: string}>('/auth/email/request', '', {email});
        setDevCode(result.development_code ?? ''); setMailSent(true);
      })}>Send code</button>
      {devCode && <p className="notice">Development sign-in code: <strong>{devCode}</strong> (no email was sent)</p>}
      {mailSent && !devCode && <p className="notice">Your code has been sent. Check your inbox and spam folder.</p>}
      <label>Verification code<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required maxLength={6} value={code} onChange={event => setCode(event.target.value)} /></label>
      <button disabled={disabled}>{busy ? 'Please wait…' : 'Sign in / Sign up →'}</button>
      {error && <p role="alert" className="error">{error}</p>}
      <small>Original fictional AI companions · Not a therapy service</small>
    </form>
  </main>;
}
