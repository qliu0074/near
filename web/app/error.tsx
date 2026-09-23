'use client';

export default function ErrorPage({reset}: {error: Error & {digest?: string}; reset: () => void}) {
  return <main className="loading"><h1>Something went wrong</h1>
    <p>Reload the page, then check your conversation before resending a message.</p>
    <button onClick={reset}>Reload page</button>
  </main>;
}
