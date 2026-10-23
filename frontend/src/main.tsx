import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type User = { id: string; name: string; email: string; organization_id: string; organization_name: string };
type Session = { authenticated: boolean; csrf_token: string; user?: User };
type ShipmentException = {
  id: string; reference: string; summary: string; details: string;
  status: 'open' | 'resolved'; priority: 'high' | 'normal';
  assignee_id: string | null; assignee_name: string | null; resolution: string | null;
  version: number; updated_at: string;
};
type Member = { id: string; name: string; email: string };
type AuditEvent = {
  id: string; action: 'created' | 'assigned' | 'resolved'; actor_name: string;
  assignee_name: string | null; note: string | null; version: number; created_at: string;
};
type Detail = { exception: ShipmentException; events: AuditEvent[] };
type CreateFields = { reference: string; summary: string; details: string; priority: 'normal' | 'high' };
type ChangeIntent = { action: 'create'; body: CreateFields } | {
  id: string; action: 'assign' | 'resolve';
  body: { expected_version: number; assignee_id: string | null } | { expected_version: number; resolution: string };
};
type PendingChange = Readonly<{ id?: string; action: 'create' | 'assign' | 'resolve'; key: string; url: string; body: string }>;
const emptyCreateFields: CreateFields = { reference: '', summary: '', details: '', priority: 'normal' };

class ApiError extends Error {
  status: number;
  code: string;
  retryAfterSeconds?: number;
  constructor(status: number, code: string, message: string, retryAfterSeconds?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function retryDelay(value: string | null): number | undefined {
  if (value === null || !/^\d+$/.test(value.trim())) return undefined;
  const seconds = Number(value);
  return Number.isInteger(seconds) && seconds >= 1 && seconds <= 60 ? seconds : undefined;
}

async function request<T>(path: string, init: RequestInit = {}, expectedStatus?: number): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, credentials: 'same-origin', cache: 'no-store' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'transport_error', 'The connection ended before a response arrived.');
  }
  if (response.status === 204) return undefined as T;
  const retryAfterSeconds = response.status === 429 ? retryDelay(response.headers.get('Retry-After')) : undefined;
  let body;
  try {
    body = await response.json();
  } catch {
    if (response.status === 429) {
      throw new ApiError(429, 'login_throttled', 'Too many sign-in attempts. Wait before trying again.', retryAfterSeconds);
    }
    throw new ApiError(0, 'unreadable_response', 'The server response could not be read.');
  }
  if (!response.ok) {
    const error = body && typeof body === 'object' ? body.error : undefined;
    throw new ApiError(response.status, typeof error?.code === 'string' ? error.code : 'request_failed',
      typeof error?.message === 'string' ? error.message : 'The request could not be completed.', retryAfterSeconds);
  }
  if (expectedStatus !== undefined && response.status !== expectedStatus) {
    throw new ApiError(0, 'unconfirmed_response', 'The response did not confirm the saved change.');
  }
  return body as T;
}

function selectedFromHash(): string | null {
  const match = /^#exception\/([a-zA-Z0-9-]+)$/.exec(window.location.hash);
  return match ? match[1] : null;
}

function creationMatchesIntent(record: ShipmentException, serializedBody: string): boolean {
  try {
    const intended = JSON.parse(serializedBody) as CreateFields;
    return record.reference === intended.reference && record.summary === intended.summary &&
      record.details === intended.details && record.priority === intended.priority &&
      record.status === 'open' && record.assignee_id === null && record.assignee_name === null &&
      record.resolution === null && typeof record.updated_at === 'string';
  } catch {
    return false;
  }
}

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function Status({ item }: { item: ShipmentException }) {
  return <span className={`status status-${item.status}`}>{item.status === 'resolved' ? 'Resolved' : 'Open'}</span>;
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [email, setEmail] = useState('alex@northline.example');
  const [password, setPassword] = useState('');
  const [loginWait, setLoginWait] = useState<{ deadline: number | null; seconds: number; missingDelay: boolean } | null>(null);
  const [items, setItems] = useState<ShipmentException[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(selectedFromHash);
  const [creating, setCreating] = useState(window.location.hash === '#new');
  const [createFields, setCreateFields] = useState<CreateFields>({ ...emptyCreateFields });
  const [detail, setDetail] = useState<Detail | null>(null);
  const [assignment, setAssignment] = useState('');
  const [resolution, setResolution] = useState('');
  const [filter, setFilter] = useState<'all' | 'open' | 'resolved'>('all');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const pendingRef = useRef<PendingChange | null>(null);
  const mutationLock = useRef(false);
  const activeUser = useRef<string | null>(null);
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  activeUser.current = session?.user?.id ?? null;

  const clearPrivateState = useCallback(() => {
    listRequest.current++; detailRequest.current++;
    setItems([]); setMembers([]); setDetail(null); setResolution('');
    setCreating(false); setCreateFields({ ...emptyCreateFields });
    setPending(null); pendingRef.current = null;
  }, []);

  const loadLists = useCallback(async (signal?: AbortSignal) => {
    const generation = ++listRequest.current;
    const user = activeUser.current;
    const [list, team] = await Promise.all([
      request<{ items: ShipmentException[] }>('/api/exceptions', { signal }),
      request<{ items: Member[] }>('/api/members', { signal }),
    ]);
    if (generation === listRequest.current && user === activeUser.current) {
      setItems(list.items); setMembers(team.items);
    }
  }, []);

  const loadDetail = useCallback(async (id: string, signal?: AbortSignal) => {
    // An old refresh must not invalidate the request for a newer selection.
    if (selectedFromHash() !== id) return;
    const generation = ++detailRequest.current;
    const user = activeUser.current;
    const result = await request<Detail>(`/api/exceptions/${encodeURIComponent(id)}`, { signal });
    if (generation === detailRequest.current && user === activeUser.current && selectedFromHash() === id) {
      setDetail(result); setAssignment(result.exception.assignee_id ?? '');
    }
    return result;
  }, []);

  const handleError = useCallback(async (failure: unknown) => {
    if (failure instanceof DOMException && failure.name === 'AbortError') return;
    if (failure instanceof ApiError && failure.status === 401) {
      clearPrivateState();
      setSession(null);
      try { setSession(await request<Session>('/api/session')); } catch { /* The sign-in view includes retry. */ }
      setError('Your session ended. Sign in again to continue.');
      return;
    }
    setError(failure instanceof Error ? failure.message : 'The request could not be completed.');
  }, [clearPrivateState]);

  useEffect(() => {
    const controller = new AbortController();
    request<Session>('/api/session', { signal: controller.signal })
      .then(setSession).catch(handleError).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [handleError]);

  useEffect(() => {
    const deadline = loginWait?.deadline;
    if (deadline === undefined || deadline === null) return;
    const timer = window.setInterval(() => {
      const seconds = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      setLoginWait(current => {
        if (current?.deadline !== deadline || current.seconds === seconds) return current;
        return { ...current, seconds, deadline: seconds === 0 ? null : deadline };
      });
    }, 250);
    return () => window.clearInterval(timer);
  }, [loginWait?.deadline]);

  useEffect(() => {
    const onHash = () => {
      setSelectedId(selectedFromHash());
      setCreating(window.location.hash === '#new');
      if (!pendingRef.current) setError('');
      setNotice(''); setConflict(false);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    if (!session?.authenticated) return;
    const controller = new AbortController();
    setLoading(true);
    loadLists(controller.signal).catch(handleError).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [session?.authenticated, loadLists, handleError]);

  useEffect(() => {
    setDetail(null); setResolution(''); setConflict(false);
    if (!session?.authenticated || !selectedId) return;
    const controller = new AbortController();
    setDetailLoading(true);
    loadDetail(selectedId, controller.signal).catch(handleError)
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [session?.authenticated, selectedId, loadDetail, handleError]);

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    const deadline = loginWait?.deadline;
    if (!session || busy || (typeof deadline === 'number' && performance.now() < deadline)) return;
    setBusy(true); setError(''); setLoginWait(null);
    try {
      const result = await request<Session>('/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token },
        body: JSON.stringify({ email, password }),
      });
      clearPrivateState(); setSession(result); setPassword(''); setNotice(''); setLoginWait(null);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 429) {
        const delay = failure.retryAfterSeconds;
        setLoginWait({ deadline: delay === undefined ? null : performance.now() + delay * 1000,
          seconds: delay ?? 0, missingDelay: delay === undefined });
        setError('Too many sign-in attempts. Wait before trying again.');
      } else {
        setError(failure instanceof Error ? failure.message : 'Sign-in could not be completed.');
      }
    }
    finally { setBusy(false); }
  }

  async function signOut() {
    if (!session || busy || pendingRef.current) return;
    setBusy(true); setError('');
    try {
      await request<void>('/api/logout', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token } });
      clearPrivateState(); setSession(null); window.location.hash = '';
      setSession(await request<Session>('/api/session')); setNotice('Signed out.');
    } catch (failure) { await handleError(failure); }
    finally { setBusy(false); }
  }

  async function refreshCurrent() {
    setBusy(true); setError('');
    try {
      await loadLists();
      if (selectedId) await loadDetail(selectedId);
      setConflict(false); setNotice('Showing the latest saved record. Review it before making another change.');
    } catch (failure) { await handleError(failure); }
    finally { setBusy(false); }
  }

  async function sendChange(intent: ChangeIntent | PendingChange) {
    if (!session || mutationLock.current) return;
    mutationLock.current = true;
    setBusy(true); setError(''); setNotice(''); setConflict(false);
    const user = activeUser.current;
    let change: PendingChange | null = null;
    let committed = false;
    try {
      // Preparation belongs inside cleanup. A key-generation failure must leave
      // the form editable without dispatching or retaining an incomplete intent.
      change = 'key' in intent ? intent : Object.freeze({
        ...('id' in intent ? { id: intent.id } : {}), action: intent.action,
        key: crypto.randomUUID(),
        url: intent.action === 'create' ? '/api/exceptions' : `/api/exceptions/${intent.id}/${intent.action}`,
        body: JSON.stringify(intent.body),
      });
      pendingRef.current = change; setPending(change);
      const result = await request<{ exception: ShipmentException }>(change.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': change.key },
        body: change.body,
      }, change.action === 'create' ? 201 : 200);
      if (!result?.exception || typeof result.exception.id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(result.exception.id) ||
          !Number.isInteger(result.exception.version) || result.exception.version < 1 ||
          (change.id !== undefined && result.exception.id !== change.id) ||
          (change.action === 'create' && (result.exception.version !== 1 || !creationMatchesIntent(result.exception, change.body)))) {
        throw new ApiError(0, 'unreadable_response', 'The saved record could not be confirmed from the response.');
      }
      committed = true;
      if (user !== activeUser.current) return;
      pendingRef.current = null; setPending(null);
      setResolution('');
      if (change.action === 'create') {
        setCreateFields({ ...emptyCreateFields }); setCreating(false); setFilter('all');
        window.location.hash = `exception/${result.exception.id}`;
      }
      await loadLists();
      if (change.action !== 'create' && change.id && selectedFromHash() === change.id) await loadDetail(change.id);
      if (user === activeUser.current) setNotice(change.action === 'create' ? 'Exception created.' : change.action === 'assign' ? 'Assignment saved.' : 'Exception resolved.');
    } catch (failure) {
      if (user !== activeUser.current) return;
      if (!change) {
        pendingRef.current = null; setPending(null);
        setError('The change could not be prepared. Nothing was sent. Try again.');
      } else if (!committed && failure instanceof ApiError && (failure.status === 0 || failure.status >= 500)) {
        setError('The response was interrupted. The change may already be saved. Retry the same change to retrieve its result.');
      } else {
        pendingRef.current = null; setPending(null);
        if (failure instanceof ApiError && failure.code === 'version_conflict') {
          setConflict(true); setError('Someone changed this exception while you were working. Refresh the record and review the latest version.');
        } else if (failure instanceof ApiError && failure.code === 'reference_conflict') {
          setError('That reference is already used in your organization. Change the reference and submit the corrected exception.');
        } else if (committed) {
          setError('Your change was saved, but the refreshed record could not be loaded. Refresh the workspace to see it.');
        } else { await handleError(failure); }
      }
    } finally { mutationLock.current = false; setBusy(false); }
  }

  function assign(event: React.FormEvent) {
    event.preventDefault();
    if (!detail || selectedFromHash() !== detail.exception.id || pendingRef.current || conflict) return;
    void sendChange({ id: detail.exception.id, action: 'assign',
      body: { expected_version: detail.exception.version, assignee_id: assignment || null } });
  }

  function resolve(event: React.FormEvent) {
    event.preventDefault();
    if (!detail || selectedFromHash() !== detail.exception.id || pendingRef.current || conflict || !resolution.trim()) return;
    void sendChange({ id: detail.exception.id, action: 'resolve',
      body: { expected_version: detail.exception.version, resolution: resolution.trim() } });
  }

  function startCreate() {
    if (busy || pendingRef.current) return;
    setCreateFields({ ...emptyCreateFields }); setError(''); setNotice('');
    setCreating(true); setSelectedId(null);
    window.location.hash = 'new';
  }

  function createException(event: React.FormEvent) {
    event.preventDefault();
    if (window.location.hash !== '#new' || busy || pendingRef.current) return;
    const body = { reference: createFields.reference.trim(), summary: createFields.summary.trim(),
      details: createFields.details.trim(), priority: createFields.priority };
    if (!body.reference || !body.summary || !body.details) {
      setError('Enter a reference, summary, and details before creating the exception.');
      return;
    }
    void sendChange({ action: 'create', body });
  }

  const visible = items.filter(item => filter === 'all' || item.status === filter);
  const openCount = items.filter(item => item.status === 'open').length;
  const locked = busy || !!pending || conflict;
  const current = detail?.exception;
  const events = detail?.events ?? [];
  const loginBlocked = loginWait !== null && loginWait.seconds > 0;

  return <>
    <div className="demo-banner"><span className="demo-dot" aria-hidden="true" /> Synthetic workspace <span className="demo-separator">/</span> Fictional organizations and shipment records</div>
    <header className="app-header">
      <div className="brand"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><div><p className="eyebrow">Shipment operations</p><p className="brand-title">Exception workspace</p></div></div>
      {session?.authenticated && session.user && <div className="identity"><div><strong>{session.user.organization_name}</strong><span>{session.user.name}</span></div><button className="button subtle" onClick={() => void signOut()} disabled={busy || !!pending}>Sign out</button></div>}
    </header>

    {!session?.authenticated ? <main className="login-layout">
      <section className="login-intro"><p className="eyebrow">Keep the handoff clear</p><h1>One exception.<br />One accountable next step.</h1><p>Review the shipment, assign a teammate, and record how it was resolved. Each saved change keeps its place in the history.</p><div className="intro-flow"><span>Review</span><span aria-hidden="true">/</span><span>Assign</span><span aria-hidden="true">/</span><span>Resolve</span></div><p className="small-print">Local demonstration using synthetic data. No live freight systems are connected.</p></section>
      <section className="login-card" aria-labelledby="sign-in-title"><p className="eyebrow">Organization access</p><h2 id="sign-in-title">Sign in to the workspace</h2><p className="muted">Use an account and password from your local seed setup.</p>
        {error && <div className="message error" role="alert">{error}</div>}
        {notice && <div className="message success" role="status">{notice}</div>}
        {loginWait && <div id="login-wait" className="login-wait" role="status" aria-live="polite" aria-atomic="true"><p>{loginWait.seconds > 0 ? `Try again in ${loginWait.seconds} ${loginWait.seconds === 1 ? 'second' : 'seconds'}.` : loginWait.missingDelay ? 'The server did not provide a usable retry time. Wait before trying again.' : 'The countdown has ended. You can try signing in again.'}</p><p>{loginWait.missingDelay ? 'The server decides when sign-in is allowed.' : 'This countdown is a local reminder. The server decides when sign-in is allowed.'}</p></div>}
        {loading ? <p role="status">Opening a session...</p> : !session ? <div><p>The session could not be opened.</p><button className="button primary" onClick={() => window.location.reload()}>Retry connection</button></div> : <form onSubmit={event => void signIn(event)}>
          <label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} maxLength={254} required disabled={busy} />
          <label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} maxLength={256} required disabled={busy} />
          <button className="button primary full-width" type="submit" disabled={busy || loginBlocked} aria-describedby={loginWait ? 'login-wait' : undefined}>{busy ? 'Signing in...' : 'Sign in'}</button>
        </form>}
        <div className="demo-accounts"><strong>Synthetic accounts</strong><span>Northline: alex@northline.example</span><span>Harbor: jules@harbor.example</span><p>Each organization sees its own records.</p></div>
      </section>
    </main> : <main className={`workspace ${selectedId || creating ? 'has-selection' : ''}`}>
      <section className="workspace-heading"><div><p className="eyebrow">Operations queue</p><h1>Shipment exceptions</h1><p className="muted">Clear ownership, current status, and the history behind each change.</p></div><div className="workspace-controls"><button className="button secondary" disabled={busy || !!pending} onClick={() => void refreshCurrent()}>Refresh workspace</button><button className="button primary" disabled={busy || !!pending || creating} onClick={startCreate}>New exception</button></div></section>
      <div className="workspace-messages">
        {error && <div className="message error" role="alert"><p>{error}</p>{conflict && <button className="button secondary" onClick={() => void refreshCurrent()} disabled={busy}>Refresh record</button>}{pending && <button className="button secondary" onClick={() => void sendChange(pending)} disabled={busy}>{busy ? 'Checking saved result...' : 'Retry same change'}</button>}</div>}
        {notice && <div className="message success" role="status">{notice}</div>}
      </div>
      <div className="work-columns">
        <section className="queue-panel" aria-labelledby="queue-title">
          <div className="panel-heading"><div><h2 id="queue-title">Your organization</h2><p>{openCount} open / {items.length} total</p></div><span className="count-marker" aria-hidden="true">{items.length.toString().padStart(2, '0')}</span></div>
          <label className="filter-label" htmlFor="status-filter">Show exceptions<select id="status-filter" aria-label="Show exceptions" value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="all">All statuses</option><option value="open">Open</option><option value="resolved">Resolved</option></select></label>
          {loading ? <p className="panel-empty" role="status">Loading exceptions...</p> : visible.length === 0 ? <p className="panel-empty">No exceptions match this status.</p> : <ul className="exception-list">{visible.map(item => <li key={item.id}><button className={`exception-row ${selectedId === item.id ? 'selected' : ''}`} onClick={() => { window.location.hash = `exception/${item.id}`; }} disabled={!!pending || busy} aria-current={selectedId === item.id ? 'true' : undefined}><span className="row-top"><span className="reference">{item.reference}</span><Status item={item} /></span><strong>{item.summary}</strong><span className="row-bottom"><span>{item.assignee_name ?? 'Unassigned'}</span><span className={`priority priority-${item.priority}`}>{item.priority === 'high' ? 'High priority' : 'Normal priority'}</span></span></button></li>)}</ul>}
        </section>

        <section className="detail-panel" aria-label="Exception detail">
          {selectedId && !creating && <button className="mobile-back button subtle" onClick={() => { window.location.hash = ''; }} disabled={busy || !!pending}>Back to exceptions</button>}
          {creating ? <section className="intake" aria-labelledby="intake-title">
            <p className="eyebrow">Manual intake</p><h2 id="intake-title">New shipment exception</h2>
            <p className="muted">Record an exception for {session.user?.organization_name}. It starts open and unassigned.</p>
            <form onSubmit={createException} aria-label="New exception">
              <label htmlFor="new-reference">Shipment reference</label><input id="new-reference" value={createFields.reference} onChange={event => setCreateFields({ ...createFields, reference: event.target.value })} maxLength={80} autoComplete="off" required disabled={locked} aria-describedby="reference-help" />
              <p id="reference-help" className="field-help">References are case-sensitive and must be unique within your organization.</p>
              <label htmlFor="new-summary">Summary</label><input id="new-summary" value={createFields.summary} onChange={event => setCreateFields({ ...createFields, summary: event.target.value })} maxLength={200} required disabled={locked} />
              <label htmlFor="new-details">Exception details</label><textarea id="new-details" rows={6} value={createFields.details} onChange={event => setCreateFields({ ...createFields, details: event.target.value })} maxLength={4000} required disabled={locked} /><span className="character-count">{createFields.details.length} / 4000</span>
              <label htmlFor="new-priority">Priority</label><select id="new-priority" value={createFields.priority} onChange={event => setCreateFields({ ...createFields, priority: event.target.value as CreateFields['priority'] })} disabled={locked}><option value="normal">Normal</option><option value="high">High</option></select>
              <div className="intake-actions"><button className="button primary" type="submit" disabled={locked || !createFields.reference.trim() || !createFields.summary.trim() || !createFields.details.trim()}>Create exception</button><button className="button secondary" type="button" onClick={() => { window.location.hash = ''; }} disabled={busy || !!pending}>Cancel intake</button></div>
            </form>
          </section> : !selectedId ? <div className="empty-detail"><div className="empty-icon" aria-hidden="true">[ ]</div><h2>Choose an exception</h2><p>Open a record to review the details, assign ownership, or document a resolution.</p></div> : detailLoading ? <p className="panel-empty" role="status">Loading record...</p> : !current ? <div className="panel-empty"><h2>Record unavailable</h2><p>Return to the queue or refresh to try again.</p></div> : <>
            <div className="detail-heading"><div><p className="reference">{current.reference}</p><h2>{current.summary}</h2></div><Status item={current} /></div>
            <div className="record-meta"><span>Version {current.version}</span><span>Updated {dateLabel(current.updated_at)}</span><span className={`priority priority-${current.priority}`}>{current.priority === 'high' ? 'High priority' : 'Normal priority'}</span></div>
            <div className="detail-description"><h3>What needs attention</h3><p>{current.details}</p></div>
            <div className="action-grid"><section className="action-card" aria-labelledby="assignment-title"><p className="eyebrow">Ownership</p><h3 id="assignment-title">Assign a teammate</h3><p className="muted">Current owner: <strong>{current.assignee_name ?? 'Unassigned'}</strong></p><form onSubmit={assign}><label htmlFor="assignee">Assigned to</label><select id="assignee" value={assignment} onChange={event => setAssignment(event.target.value)} disabled={locked || current.status === 'resolved'}><option value="">Unassigned</option>{members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select><button className="button secondary" type="submit" disabled={locked || current.status === 'resolved' || assignment === (current.assignee_id ?? '')}>Save assignment</button></form></section>
              <section className="action-card" aria-labelledby="resolution-title"><p className="eyebrow">Outcome</p><h3 id="resolution-title">{current.status === 'resolved' ? 'Resolution recorded' : 'Resolve exception'}</h3>{current.status === 'resolved' ? <><p className="resolution-text">{current.resolution}</p><p className="muted small-print">This record is resolved. Its history remains available below.</p></> : <form onSubmit={resolve}><label htmlFor="resolution">Resolution note</label><textarea id="resolution" rows={4} placeholder="Describe what changed and the next handoff." value={resolution} onChange={event => setResolution(event.target.value)} maxLength={2000} required disabled={locked} /><span className="character-count">{resolution.length} / 2000</span><button className="button primary" type="submit" disabled={locked || !resolution.trim()}>Confirm resolution</button></form>}</section>
            </div>
            <section className="history" aria-labelledby="history-title"><div className="history-heading"><h3 id="history-title">Change history</h3><span>{events.length} saved {events.length === 1 ? 'change' : 'changes'}</span></div>{events.length === 0 ? <p className="muted">No changes recorded yet. The seeded record starts at version {current.version}.</p> : <ol className="history-list">{events.map(event => <li key={event.id}><span className="history-dot" aria-hidden="true" /><div><p><strong>{event.actor_name}</strong> {event.action === 'created' ? 'created the exception' : event.action === 'resolved' ? 'resolved the exception' : event.assignee_name ? `assigned ${event.assignee_name}` : 'removed the assignment'}</p>{event.note && <p className="history-note">{event.note}</p>}<p className="history-meta">Version {event.version} / {dateLabel(event.created_at)}</p></div></li>)}</ol>}</section>
          </>}
        </section>
      </div>
    </main>}
    <footer className="app-footer"><span>Shipment Exception Workspace</span><span>Synthetic data / Local demonstration</span><a href="/third-party-notices" target="_blank" rel="noreferrer">Dependency notices</a></footer>
  </>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
