type Props = {loading: boolean; error: string; retry: () => Promise<unknown>; empty?: boolean};

export function ReadStatus({loading, error, retry, empty = false}: Props) {
  if (error) return <div className="error" role="alert">{error} <button className="text" onClick={() => void retry()}>Reload</button></div>;
  if (loading) return <div role="status" className={empty ? 'skeleton' : 'read-status'} aria-label="Loading">
    {empty ? <><span/><span/><span/></> : 'Updating…'}
  </div>;
  return null;
}
