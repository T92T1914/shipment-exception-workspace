import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { adoptSessionContext, captureSessionContext, matchesSessionContext, openSessionChannel,
  retireSessionContext, StaleSessionResponse } from './session_sync';

type User = { id: string; name: string; email: string; organization_id: string; organization_name: string; role: 'operator' | 'reviewer' };
type Session = { authenticated: boolean; csrf_token: string; session_context: string; user?: User };
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
type HistoryMetadata = { next_cursor: string | null; page_size: number; through_version: number };
type HistoryPage = HistoryMetadata & { events: AuditEvent[] };
type Detail = { exception: ShipmentException; events: AuditEvent[]; history: HistoryMetadata };
type HistoryView = { id: string; cursors: (string | null)[]; index: number; throughVersion: number };
type QueueStatus = 'all' | 'open' | 'resolved';
type QueueRequest = { status: QueueStatus; q: string; cursors: (string | null)[]; index: number };
type QueuePage = { items: ShipmentException[]; next_cursor: string | null; page_size: number };
type CreateFields = { reference: string; summary: string; details: string; priority: 'normal' | 'high' };
type ChangeIntent = { action: 'create'; body: CreateFields } | {
  id: string; action: 'assign' | 'resolve';
  body: { expected_version: number; assignee_id: string | null } | { expected_version: number; resolution: string };
};
type PendingChange = Readonly<{ id?: string; action: 'create' | 'assign' | 'resolve'; key: string; url: string; body: string }>;
const emptyCreateFields: CreateFields = { reference: '', summary: '', details: '', priority: 'normal' };
const firstQueuePage = (status: QueueStatus = 'all', q = ''): QueueRequest => ({ status, q, cursors: [null], index: 0 });

function queuePath(view: QueueRequest): string {
  const params = new URLSearchParams();
  if (view.status !== 'all') params.set('status', view.status);
  if (view.q) params.set('q', view.q);
  const cursor = view.cursors[view.index];
  if (cursor) params.set('cursor', cursor);
  // The API's default page is 20. Keep a plain first-page URL when no filter is
  // applied, while explicitly carrying the page size with continuation context.
  if (params.size) params.set('limit', '20');
  return `/api/exceptions${params.size ? `?${params.toString()}` : ''}`;
}

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
  const snapshot = captureSessionContext();
  const headers = new Headers(init.headers);
  if (path !== '/api/session' && snapshot.context) headers.set('X-Workspace-Context', snapshot.context);
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, credentials: 'same-origin', cache: 'no-store' });
  } catch (error) {
    if (!matchesSessionContext(snapshot)) throw new StaleSessionResponse();
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'transport_error', 'The connection ended before a response arrived.');
  }
  if (response.status === 204) {
    if (!matchesSessionContext(snapshot)) throw new StaleSessionResponse();
    return undefined as T;
  }
  const retryAfterSeconds = response.status === 429 ? retryDelay(response.headers.get('Retry-After')) : undefined;
  let body;
  try {
    // Consume an admitted body even when its session changed. The stale result
    // is rejected below before status handling or a caller can use its data.
    body = await response.json();
  } catch {
    if (!matchesSessionContext(snapshot)) throw new StaleSessionResponse();
    if (response.status === 429) {
      throw new ApiError(429, 'login_throttled', 'Too many sign-in attempts. Wait before trying again.', retryAfterSeconds);
    }
    throw new ApiError(0, 'unreadable_response', 'The server response could not be read.');
  }
  if (!matchesSessionContext(snapshot)) throw new StaleSessionResponse();
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

function sessionProblem(failure: unknown): failure is ApiError {
  return failure instanceof ApiError && (failure.status === 401 || failure.code === 'session_changed');
}

function sameIdentity(left: Session, right: Session) {
  return left.authenticated === right.authenticated && left.user?.id === right.user?.id &&
    left.user?.organization_id === right.user?.organization_id;
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

function readableHistory(page: HistoryPage, throughVersion?: number): boolean {
  return !!page && Array.isArray(page.events) && page.events.length <= 20 && page.page_size === 20 &&
    Number.isInteger(page.through_version) && page.through_version >= 1 &&
    (throughVersion === undefined || page.through_version === throughVersion) &&
    (page.next_cursor === null || (typeof page.next_cursor === 'string' && !!page.next_cursor && page.next_cursor.length <= 1024)) &&
    page.events.every((event, index, events) => !!event && Number.isInteger(event.version) && event.version >= 1 &&
      event.version <= page.through_version && (index === 0 || events[index - 1].version < event.version));
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
  const [historyPage, setHistoryPage] = useState<HistoryPage | null>(null);
  const [historyView, setHistoryView] = useState<HistoryView | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [assignment, setAssignment] = useState('');
  const [resolution, setResolution] = useState('');
  const [queue, setQueue] = useState<QueueRequest>(firstQueuePage);
  const [searchDraft, setSearchDraft] = useState('');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [queueError, setQueueError] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusy, setBusy] = useState(false);
  const [sessionChecking, setSessionChecking] = useState(false);
  const [sessionCheckError, setSessionCheckError] = useState(false);
  const [sessionMessage, setSessionMessage] = useState('');
  const busy = actionBusy || sessionChecking;
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<PendingChange | null>(null);
  const pendingRef = useRef<PendingChange | null>(null);
  const mutationLock = useRef<symbol | null>(null);
  const actionOwner = useRef<symbol | null>(null);
  const mounted = useRef(true);
  const sessionValue = useRef(session);
  const syncWork = useRef<Promise<void> | null>(null);
  const syncAgain = useRef(false);
  const notifier = useRef<ReturnType<typeof openSessionChannel> | null>(null);
  const retiredUncertain = useRef(false);
  const activeUser = useRef<string | null>(null);
  const activeRole = useRef<string | undefined>(undefined);
  const accessRequest = useRef(0);
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  const historyRequest = useRef(0);
  const historyRef = useRef<HistoryView | null>(null);
  const firstHistoryPage = useRef<HistoryPage | null>(null);
  const historyBusy = useRef(false);
  const queueRef = useRef(queue);
  const queueBusy = useRef(false);
  activeUser.current = session?.user?.id ?? null;
  activeRole.current = session?.user?.role;
  sessionValue.current = session;
  const canMutate = session?.user?.role === 'operator';

  const clearHistory = useCallback(() => {
    historyRequest.current++;
    historyRef.current = null; firstHistoryPage.current = null; historyBusy.current = false;
    setHistoryView(null); setHistoryPage(null); setHistoryError(''); setHistoryLoading(false);
  }, []);

  const clearPrivateState = useCallback(() => {
    listRequest.current++; detailRequest.current++; accessRequest.current++;
    activeRole.current = undefined;
    setItems([]); setMembers([]); setDetail(null); setResolution(''); setAssignment('');
    const reset = firstQueuePage();
    queueRef.current = reset; setQueue(reset); setSearchDraft('');
    queueBusy.current = false;
    setNextCursor(null); setQueueError(''); setQueueLoading(false);
    setCreating(false); setCreateFields({ ...emptyCreateFields });
    setPending(null); pendingRef.current = null;
    clearHistory();
  }, [clearHistory]);

  const installSession = useCallback((value: Session) => {
    adoptSessionContext(value.session_context);
    activeUser.current = value.user?.id ?? null;
    activeRole.current = value.user?.role;
    sessionValue.current = value;
    setSession(value);
  }, []);

  const retireWorkspace = useCallback((message: string) => {
    const uncertain = retiredUncertain.current || !!pendingRef.current || !!mutationLock.current;
    retiredUncertain.current = uncertain;
    retireSessionContext();
    clearPrivateState();
    activeUser.current = null; activeRole.current = undefined;
    actionOwner.current = null; mutationLock.current = null;
    sessionValue.current = null;
    setSession(null); setBusy(false); setPassword(''); setLoginWait(null);
    setConflict(false); setNotice(''); setSelectedId(null); setDetailLoading(false);
    window.location.hash = '';
    setError('');
    setSessionMessage(uncertain ? `${message} An earlier change may already be saved. Its local retry was retired. Review saved records before new work.` : message);
  }, [clearPrivateState]);

  const retireReadOnlyIntent = useCallback((value: Session) => {
    if (value.user?.role === 'reviewer' && pendingRef.current) {
      // A successful session read can remove replay permission before a POST
      // reports read_only. Retire its epoch too, so a delayed completion cannot
      // restore the old operator view or clear a newer action's busy state.
      retireWorkspace('Your current access is read-only. Review saved records before continuing.');
    }
  }, [retireWorkspace]);

  const synchronizeSession = useCallback((retire = false, message = 'Your account or session changed. Review the current workspace before new work.') => {
    if (retire) retireWorkspace(message);
    syncAgain.current = true;
    if (syncWork.current) return syncWork.current;
    setSessionChecking(true); setSessionCheckError(false);
    const work = (async () => {
      while (syncAgain.current && mounted.current) {
        syncAgain.current = false;
        const snapshot = captureSessionContext();
        const expected = sessionValue.current;
        const generation = ++accessRequest.current;
        try {
          const value = await request<Session>('/api/session');
          if (!mounted.current || !matchesSessionContext(snapshot) || generation !== accessRequest.current) continue;
          if ((snapshot.context !== null && snapshot.context !== value.session_context) ||
              (expected && !sameIdentity(expected, value))) retireWorkspace(message);
          else retireReadOnlyIntent(value);
          installSession(value);
          setSessionCheckError(false);
        } catch (failure) {
          if (!mounted.current || failure instanceof StaleSessionResponse || !matchesSessionContext(snapshot)) continue;
          retireWorkspace('The current session could not be confirmed. Check the session before continuing.');
          setSessionCheckError(true);
        }
      }
    })();
    syncWork.current = work;
    void work.finally(() => {
      if (syncWork.current !== work) return;
      syncWork.current = null;
      if (mounted.current) { setSessionChecking(false); setLoading(false); }
    });
    return work;
  }, [installSession, retireReadOnlyIntent, retireWorkspace]);

  function beginAction() {
    const owner = Symbol();
    actionOwner.current = owner; setBusy(true);
    return owner;
  }

  function finishAction(owner: symbol) {
    if (actionOwner.current !== owner) return;
    actionOwner.current = null; setBusy(false);
  }

  const refreshAccess = useCallback(async (user: string | null) => {
    const snapshot = captureSessionContext();
    // Explicit reads join the same owner as lifecycle checks, including its
    // queued trailing check. A matching background read cannot discard the
    // user's refresh, and an older response cannot reinstall obsolete access.
    await synchronizeSession();
    if (!mounted.current || user !== activeUser.current || !matchesSessionContext(snapshot)) return null;
    const result = sessionValue.current;
    if (!result?.authenticated || !result.user || result.user.id !== user ||
        result.session_context !== snapshot.context) return null;
    return result;
  }, [synchronizeSession]);

  const beginQueue = useCallback((view: QueueRequest) => {
    // Invalidate synchronously: an older response can arrive before React has
    // rendered the new query or page selection.
    listRequest.current++;
    queueBusy.current = true;
    queueRef.current = view; setQueue(view);
    setItems([]); setNextCursor(null); setQueueError(''); setQueueLoading(true);
    return view;
  }, []);

  const loadLists = useCallback(async (view: QueueRequest, signal?: AbortSignal) => {
    const snapshot = captureSessionContext();
    const generation = ++listRequest.current;
    const user = activeUser.current;
    const current = () => generation === listRequest.current && user === activeUser.current && view === queueRef.current && matchesSessionContext(snapshot);
    setQueueLoading(true);
    try {
      const [list, team] = await Promise.all([
        request<QueuePage>(queuePath(view), { signal }),
        request<{ items: Member[] }>('/api/members', { signal }),
      ]);
      if (!current()) return false;
      if (!Array.isArray(list.items) || list.items.length > 20 || list.page_size !== 20 ||
          (list.next_cursor !== null && (typeof list.next_cursor !== 'string' || !list.next_cursor || list.next_cursor.length > 2048))) {
        throw new ApiError(0, 'unreadable_queue', 'The queue response could not be read.');
      }
      setItems(list.items); setNextCursor(list.next_cursor); setMembers(team.items); setQueueError('');
      return true;
    } catch (failure) {
      if (!current() || (failure instanceof DOMException && failure.name === 'AbortError')) return false;
      if (!(failure instanceof ApiError && failure.status === 401)) {
        setQueueError('The queue could not be loaded. Change the search or return to the first page.');
      }
      throw failure;
    } finally {
      if (current()) { queueBusy.current = false; setQueueLoading(false); }
    }
  }, []);

  const loadDetail = useCallback(async (id: string, signal?: AbortSignal) => {
    // An old refresh must not invalidate the request for a newer selection.
    if (selectedFromHash() !== id) return;
    const generation = ++detailRequest.current;
    const snapshot = captureSessionContext();
    const user = activeUser.current;
    clearHistory();
    setHistoryLoading(true);
    try {
      const result = await request<Detail>(`/api/exceptions/${encodeURIComponent(id)}`, { signal });
      if (generation === detailRequest.current && user === activeUser.current && selectedFromHash() === id && matchesSessionContext(snapshot)) {
        const first = { ...result.history, events: result.events };
        if (!readableHistory(first) || first.through_version !== result.exception.version) {
          throw new ApiError(0, 'unreadable_history', 'The change history could not be read. Refresh the workspace to try again.');
        }
        setDetail(result); setAssignment(result.exception.assignee_id ?? '');
        const view = { id, cursors: [null], index: 0, throughVersion: first.through_version };
        historyRef.current = view; firstHistoryPage.current = first;
        setHistoryView(view); setHistoryPage(first);
      }
      return result;
    } catch (failure) {
      if (generation === detailRequest.current && user === activeUser.current && selectedFromHash() === id && matchesSessionContext(snapshot) &&
          !(failure instanceof DOMException && failure.name === 'AbortError')) {
        setHistoryError('The latest history could not be loaded. Refresh the workspace to try again.');
      }
      throw failure;
    } finally {
      if (generation === detailRequest.current && user === activeUser.current && selectedFromHash() === id && matchesSessionContext(snapshot)) setHistoryLoading(false);
    }
  }, [clearHistory]);

  const handleError = useCallback(async (failure: unknown) => {
    if (failure instanceof StaleSessionResponse || (failure instanceof DOMException && failure.name === 'AbortError')) return;
    if (sessionProblem(failure)) {
      await synchronizeSession(true);
      return;
    }
    setError(failure instanceof Error ? failure.message : 'The request could not be completed.');
  }, [synchronizeSession]);

  useEffect(() => {
    const controller = new AbortController();
    request<Session>('/api/session', { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) installSession(value); })
      .catch(handleError).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [handleError, installSession]);

  useEffect(() => {
    mounted.current = true;
    notifier.current = openSessionChannel(() => { void synchronizeSession(true); });
    const check = () => {
      if (document.visibilityState === 'visible' && sessionValue.current) void synchronizeSession();
    };
    const shown = (event: PageTransitionEvent) => { if (event.persisted) check(); };
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    window.addEventListener('pageshow', shown);
    return () => {
      mounted.current = false;
      accessRequest.current++;
      notifier.current?.close(); notifier.current = null;
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', check);
      window.removeEventListener('pageshow', shown);
    };
  }, [synchronizeSession]);

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
      clearHistory();
      setSelectedId(selectedFromHash());
      setCreating(window.location.hash === '#new');
      if (!pendingRef.current && activeRole.current === 'operator') setError('');
      setNotice(''); setConflict(false);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [clearHistory]);

  useEffect(() => {
    if (session?.authenticated && !canMutate && creating) {
      setCreating(false); setCreateFields({ ...emptyCreateFields });
      if (window.location.hash === '#new') window.location.hash = '';
    }
  }, [session?.authenticated, canMutate, creating]);

  useEffect(() => {
    if (!session?.authenticated) return;
    const controller = new AbortController();
    const view = beginQueue(queueRef.current);
    const user = activeUser.current;
    loadLists(view, controller.signal).catch(failure => {
      if (view === queueRef.current && user === activeUser.current && sessionProblem(failure)) void handleError(failure);
    });
    return () => controller.abort();
  }, [session?.authenticated, session?.user?.id, session?.user?.organization_id, session?.user?.role, session?.session_context, beginQueue, loadLists, handleError]);

  useEffect(() => {
    setDetail(null); setResolution(''); setConflict(false);
    clearHistory();
    if (!session?.authenticated || !selectedId) return;
    const controller = new AbortController();
    setDetailLoading(true);
    loadDetail(selectedId, controller.signal).catch(handleError)
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [session?.authenticated, session?.session_context, selectedId, loadDetail, handleError, clearHistory]);

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    const deadline = loginWait?.deadline;
    if (!session || busy || (typeof deadline === 'number' && performance.now() < deadline)) return;
    const owner = beginAction();
    const snapshot = captureSessionContext();
    setError(''); setLoginWait(null);
    try {
      const result = await request<Session>('/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token },
        body: JSON.stringify({ email, password }),
      });
      if (actionOwner.current !== owner || !matchesSessionContext(snapshot)) return;
      clearPrivateState(); installSession(result); setPassword(''); setNotice(''); setLoginWait(null);
      notifier.current?.notify();
    } catch (failure) {
      if (actionOwner.current !== owner || !matchesSessionContext(snapshot)) return;
      if (failure instanceof StaleSessionResponse) return;
      // A rejected password leaves the current anonymous session usable.
      // Only an explicit context mismatch needs account reconciliation here.
      if (failure instanceof ApiError && failure.code === 'session_changed') { await handleError(failure); }
      else if (failure instanceof ApiError && failure.status === 429) {
        const delay = failure.retryAfterSeconds;
        setLoginWait({ deadline: delay === undefined ? null : performance.now() + delay * 1000,
          seconds: delay ?? 0, missingDelay: delay === undefined });
        setError('Too many sign-in attempts. Wait before trying again.');
      } else {
        setError(failure instanceof Error ? failure.message : 'Sign-in could not be completed.');
      }
    }
    finally { finishAction(owner); }
  }

  async function signOut() {
    if (!session || busy || pendingRef.current) return;
    const owner = beginAction();
    const snapshot = captureSessionContext();
    setError('');
    try {
      await request<void>('/api/logout', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token } });
      if (actionOwner.current !== owner || !matchesSessionContext(snapshot)) return;
      retireWorkspace('');
      // Establish the next anonymous cookie before notifying other tabs. They
      // can then read that session instead of all creating anonymous cookies.
      await synchronizeSession();
      notifier.current?.notify();
    } catch (failure) {
      if (actionOwner.current === owner && matchesSessionContext(snapshot)) await handleError(failure);
    }
    finally { finishAction(owner); }
  }

  async function refreshCurrent() {
    if (busy || pendingRef.current) return;
    const owner = beginAction();
    const snapshot = captureSessionContext();
    setError('');
    const user = activeUser.current;
    let view: QueueRequest | undefined;
    try {
      if (!await refreshAccess(user)) return;
      view = beginQueue(firstQueuePage(queueRef.current.status, queueRef.current.q));
      await loadLists(view);
      if (user !== activeUser.current || !matchesSessionContext(snapshot)) return;
      if (selectedId) await loadDetail(selectedId);
      if (user === activeUser.current && matchesSessionContext(snapshot)) {
        setConflict(false); setNotice('Showing the first queue page and the latest saved record. Review it before making another change.');
      }
    } catch (failure) { if (user === activeUser.current && (!view || view === queueRef.current)) await handleError(failure); }
    finally { finishAction(owner); }
  }

  async function browseQueue(view: QueueRequest) {
    if (busy || pendingRef.current) return;
    const user = activeUser.current;
    beginQueue(view); setNotice('');
    try { await loadLists(view); }
    catch (failure) {
      if (view === queueRef.current && user === activeUser.current && sessionProblem(failure)) await handleError(failure);
    }
  }

  function searchQueue(event: React.FormEvent) {
    event.preventDefault();
    if (busy || pendingRef.current) return;
    const q = searchDraft.trim();
    setSearchDraft(q);
    void browseQueue(firstQueuePage(queueRef.current.status, q));
  }

  function changeQueueStatus(status: QueueStatus) {
    void browseQueue(firstQueuePage(status, queueRef.current.q));
  }

  function clearSearch() {
    if (busy || pendingRef.current) return;
    setSearchDraft('');
    void browseQueue(firstQueuePage(queueRef.current.status));
  }

  function nextPage() {
    if (queueBusy.current || !nextCursor) return;
    const view = queueRef.current;
    void browseQueue({ ...view, cursors: [...view.cursors.slice(0, view.index + 1), nextCursor], index: view.index + 1 });
  }

  function previousPage() {
    const view = queueRef.current;
    if (queueBusy.current || view.index === 0) return;
    void browseQueue({ ...view, index: view.index - 1 });
  }

  async function browseHistory(view: HistoryView) {
    if (busy || pendingRef.current || historyBusy.current || selectedFromHash() !== view.id) return;
    const generation = ++historyRequest.current;
    const snapshot = captureSessionContext();
    const recordGeneration = detailRequest.current;
    const user = activeUser.current;
    const current = () => generation === historyRequest.current && recordGeneration === detailRequest.current &&
      user === activeUser.current && selectedFromHash() === view.id && historyRef.current === view && matchesSessionContext(snapshot);
    historyRef.current = view; historyBusy.current = true;
    setHistoryView(view); setHistoryPage(null); setHistoryError(''); setHistoryLoading(true);
    try {
      // Keep just the first bounded page for returning to this browse's ceiling.
      // A fresh no-cursor GET would instead start at a newer record version.
      const page = view.index === 0 ? firstHistoryPage.current : await request<HistoryPage>(
        `/api/exceptions/${encodeURIComponent(view.id)}/history?${new URLSearchParams({ limit: '20', cursor: view.cursors[view.index]! })}`,
      );
      if (!current()) return;
      if (!page || !readableHistory(page, view.throughVersion)) {
        throw new ApiError(0, 'unreadable_history', 'The change history response could not be read.');
      }
      setHistoryPage(page);
    } catch (failure) {
      if (!current()) return;
      if (sessionProblem(failure)) {
        await handleError(failure);
      } else {
        setHistoryError('This history page could not be loaded. Retry the page or refresh the latest changes.');
      }
    } finally {
      if (current()) { historyBusy.current = false; setHistoryLoading(false); }
    }
  }

  function olderChanges() {
    const view = historyRef.current;
    if (!view || !historyPage?.next_cursor) return;
    void browseHistory({ ...view, cursors: [...view.cursors.slice(0, view.index + 1), historyPage.next_cursor], index: view.index + 1 });
  }

  function newerChanges() {
    const view = historyRef.current;
    if (!view || view.index === 0) return;
    void browseHistory({ ...view, index: view.index - 1 });
  }

  async function sendChange(intent: ChangeIntent | PendingChange) {
    if (!session || busy || activeRole.current !== 'operator' || mutationLock.current) return;
    const owner = beginAction();
    mutationLock.current = owner;
    const snapshot = captureSessionContext();
    retiredUncertain.current = false; setSessionMessage('');
    setError(''); setNotice(''); setConflict(false);
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
      if (user !== activeUser.current || !matchesSessionContext(snapshot)) return;
      pendingRef.current = null; setPending(null);
      setResolution('');
      if (change.action === 'create') {
        setCreateFields({ ...emptyCreateFields }); setCreating(false); setSearchDraft('');
        window.location.hash = `exception/${result.exception.id}`;
      }
      const view = beginQueue(change.action === 'create' ? firstQueuePage() : firstQueuePage(queueRef.current.status, queueRef.current.q));
      await loadLists(view);
      if (change.action !== 'create' && change.id && selectedFromHash() === change.id) await loadDetail(change.id);
      if (user === activeUser.current && matchesSessionContext(snapshot)) setNotice(change.action === 'create' ? 'Exception created.' : change.action === 'assign' ? 'Assignment saved.' : 'Exception resolved.');
    } catch (failure) {
      if (user !== activeUser.current || !matchesSessionContext(snapshot) || failure instanceof StaleSessionResponse) return;
      if (sessionProblem(failure)) {
        await handleError(failure);
      } else if (!change) {
        pendingRef.current = null; setPending(null);
        setError('The change could not be prepared. Nothing was sent. Try again.');
      } else if (!committed && failure instanceof ApiError && (failure.status === 0 || failure.status >= 500)) {
        setError('The response was interrupted. The change may already be saved. Retry the same change to retrieve its result.');
      } else {
        pendingRef.current = null; setPending(null);
        if (failure instanceof ApiError && failure.status === 403 && failure.code === 'read_only') {
          // A denied replay says nothing about an earlier interrupted commit.
          // Retire this tab's intent and review current records before new work.
          activeRole.current = 'reviewer';
          setSession(value => !value?.user || value.user.id !== user ? value : { ...value, user: { ...value.user, role: 'reviewer' } });
          setCreating(false); setCreateFields({ ...emptyCreateFields });
          if (window.location.hash === '#new') window.location.hash = '';
          setError('This attempt was denied because your current access is read-only. An earlier interrupted request may already be saved. Refresh the workspace to review saved records.');
          try { await refreshAccess(user); } catch { /* Remain read-only until an explicit access refresh succeeds. */ }
        } else if (failure instanceof ApiError && failure.code === 'version_conflict') {
          setConflict(true); setError('Someone changed this exception while you were working. Refresh the record and review the latest version.');
        } else if (failure instanceof ApiError && failure.code === 'reference_conflict') {
          setError('That reference is already used in your organization. Change the reference and submit the corrected exception.');
        } else if (committed) {
          setError('Your change was saved, but the refreshed record could not be loaded. Refresh the workspace to see it.');
        } else { await handleError(failure); }
      }
    } finally {
      if (mutationLock.current === owner) mutationLock.current = null;
      finishAction(owner);
    }
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
    if (activeRole.current !== 'operator' || busy || pendingRef.current) return;
    setCreateFields({ ...emptyCreateFields }); setError(''); setNotice('');
    setCreating(true); setSelectedId(null);
    window.location.hash = 'new';
  }

  function createException(event: React.FormEvent) {
    event.preventDefault();
    if (activeRole.current !== 'operator' || window.location.hash !== '#new' || busy || pendingRef.current) return;
    const body = { reference: createFields.reference.trim(), summary: createFields.summary.trim(),
      details: createFields.details.trim(), priority: createFields.priority };
    if (!body.reference || !body.summary || !body.details) {
      setError('Enter a reference, summary, and details before creating the exception.');
      return;
    }
    void sendChange({ action: 'create', body });
  }

  const locked = busy || !!pending || conflict || !canMutate;
  const current = detail?.exception;
  const events = historyPage?.events ?? [];
  const loginBlocked = loginWait !== null && loginWait.seconds > 0;
  const selectedOutsidePage = !!current && !queueLoading && !queueError && !items.some(item => item.id === current.id);

  return <>
    <div className="demo-banner"><span className="demo-dot" aria-hidden="true" /> Synthetic workspace <span className="demo-separator">/</span> Fictional organizations and shipment records</div>
    <header className="app-header">
      <div className="brand"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span><div><p className="eyebrow">Shipment operations</p><p className="brand-title">Exception workspace</p></div></div>
      {session?.authenticated && session.user && <div className="identity"><div><strong>{session.user.organization_name}</strong><span>{session.user.name}</span><span className="access-role">{canMutate ? 'Operator' : 'Read-only reviewer'}</span></div><button className="button subtle" onClick={() => void signOut()} disabled={busy || !!pending}>Sign out</button></div>}
    </header>

    {!session?.authenticated ? <main className="login-layout">
      <section className="login-intro"><p className="eyebrow">Keep the handoff clear</p><h1>One exception.<br />One accountable next step.</h1><p>Review the shipment, assign a teammate, and record how it was resolved. Each saved change keeps its place in the history.</p><div className="intro-flow"><span>Review</span><span aria-hidden="true">/</span><span>Assign</span><span aria-hidden="true">/</span><span>Resolve</span></div><p className="small-print">Local demonstration using synthetic data. No live freight systems are connected.</p></section>
      <section className="login-card" aria-labelledby="sign-in-title"><p className="eyebrow">Organization access</p><h2 id="sign-in-title">Sign in to the workspace</h2><p className="muted">Use an account and password from your local seed setup.</p>
        {error && <div className="message error" role="alert">{error}</div>}
        {sessionMessage && <div className="message error session-message" role="alert">{sessionMessage}</div>}
        {notice && <div className="message success" role="status">{notice}</div>}
        {loginWait && <div id="login-wait" className="login-wait" role="status" aria-live="polite" aria-atomic="true"><p>{loginWait.seconds > 0 ? `Try again in ${loginWait.seconds} ${loginWait.seconds === 1 ? 'second' : 'seconds'}.` : loginWait.missingDelay ? 'The server did not provide a usable retry time. Wait before trying again.' : 'The countdown has ended. You can try signing in again.'}</p><p>{loginWait.missingDelay ? 'The server decides when sign-in is allowed.' : 'This countdown is a local reminder. The server decides when sign-in is allowed.'}</p></div>}
        {loading ? <p role="status">Opening a session...</p> : sessionCheckError || !session ? <div><p>The current session could not be confirmed.</p><button className="button primary" disabled={busy} onClick={() => void synchronizeSession()}>Check current session</button></div> : <form onSubmit={event => void signIn(event)}>
          <label htmlFor="email">Email address</label><input id="email" name="email" type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} maxLength={254} required disabled={busy} />
          <label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} maxLength={256} required disabled={busy} />
          <button className="button primary full-width" type="submit" disabled={busy || loginBlocked} aria-describedby={loginWait ? 'login-wait' : undefined}>{busy ? 'Signing in...' : 'Sign in'}</button>
        </form>}
        <div className="demo-accounts"><strong>Synthetic accounts</strong><span>Operators: alex@northline.example, jules@harbor.example</span><span>Reviewers: casey@northline.example, taylor@harbor.example</span><p>Each organization sees its own records.</p></div>
      </section>
    </main> : <main className={`workspace ${selectedId || creating ? 'has-selection' : ''}`}>
      <section className="workspace-heading"><div><p className="eyebrow">Operations queue</p><h1>Shipment exceptions</h1><p className="muted">Clear ownership, current status, and the history behind each change.</p></div><div className="workspace-controls"><button className="button secondary" disabled={busy || !!pending} onClick={() => void refreshCurrent()}>Refresh workspace</button>{canMutate && <button className="button primary" disabled={busy || !!pending || creating} onClick={startCreate}>New exception</button>}</div></section>
      {!canMutate && <section className="access-notice" aria-label="Read-only access"><h2>Read-only access</h2><p>You can browse your organization's exceptions and change history. Creating, assigning and resolving exceptions requires an operator.</p></section>}
      <div className="workspace-messages">
        {sessionMessage && <div className="message error session-message" role="alert">{sessionMessage}</div>}
        {error && <div className="message error" role="alert"><p>{error}</p>{conflict && <button className="button secondary" onClick={() => void refreshCurrent()} disabled={busy}>Refresh record</button>}{pending && <button className="button secondary" onClick={() => void sendChange(pending)} disabled={busy || !canMutate}>{busy ? 'Checking saved result...' : 'Retry same change'}</button>}</div>}
        {notice && <div className="message success" role="status">{notice}</div>}
      </div>
      <div className="work-columns">
        <section className="queue-panel" aria-labelledby="queue-title">
          <div className="panel-heading"><div><h2 id="queue-title">Your organization</h2><p aria-live="polite">{queueLoading ? `Loading page ${queue.index + 1}` : `${items.length} on this page / Page ${queue.index + 1}`}</p></div><span className="count-marker" aria-hidden="true">{items.length.toString().padStart(2, '0')}</span></div>
          <form className="queue-search" onSubmit={searchQueue} aria-label="Search exception queue">
            <label htmlFor="queue-search">Search references and summaries</label>
            <input id="queue-search" type="search" value={searchDraft} onChange={event => setSearchDraft(event.target.value)} maxLength={80} disabled={busy || !!pending} autoComplete="off" />
            <div className="queue-search-actions"><button className="button secondary" type="submit" disabled={busy || !!pending}>Search queue</button><button className="button secondary" type="button" onClick={clearSearch} disabled={busy || !!pending || (!searchDraft && !queue.q)}>Clear search</button></div>
            {queue.q && <p className="queue-query">Results for <strong>{queue.q}</strong></p>}
          </form>
          <label className="filter-label" htmlFor="status-filter">Show exceptions<select id="status-filter" aria-label="Show exceptions" value={queue.status} onChange={event => changeQueueStatus(event.target.value as QueueStatus)} disabled={busy || !!pending}><option value="all">All statuses</option><option value="open">Open</option><option value="resolved">Resolved</option></select></label>
          {queueError ? <div className="panel-empty queue-error" role="alert"><p>{queueError}</p><button className="button secondary" type="button" onClick={() => void browseQueue(firstQueuePage(queueRef.current.status, queueRef.current.q))} disabled={busy || !!pending}>Return to first page</button></div> : queueLoading ? <p className="panel-empty" role="status">Loading exceptions...</p> : items.length === 0 ? <div className="panel-empty"><p>No exceptions match this search and status on this page.</p>{queue.index > 0 && <button className="button secondary" type="button" onClick={() => void browseQueue(firstQueuePage(queueRef.current.status, queueRef.current.q))} disabled={busy || !!pending}>Return to first page</button>}</div> : <ul className="exception-list">{items.map(item => <li key={item.id}><button className={`exception-row ${selectedId === item.id ? 'selected' : ''}`} onClick={() => { window.location.hash = `exception/${item.id}`; }} disabled={!!pending || busy} aria-current={selectedId === item.id ? 'true' : undefined}><span className="row-top"><span className="reference" translate="no">{item.reference}</span><Status item={item} /></span><strong>{item.summary}</strong><span className="row-bottom"><span>{item.assignee_name ?? 'Unassigned'}</span><span className={`priority priority-${item.priority}`}>{item.priority === 'high' ? 'High priority' : 'Normal priority'}</span></span></button></li>)}</ul>}
          <nav className="queue-pages" aria-label="Exception queue pages"><button className="button secondary" type="button" onClick={previousPage} disabled={busy || !!pending || queueLoading || queue.index === 0}>Previous page</button><span>Page {queue.index + 1}</span><button className="button secondary" type="button" onClick={nextPage} disabled={busy || !!pending || queueLoading || !!queueError || !nextCursor}>Next page</button></nav>
          <p className="queue-live-note">Pages show live results. Refresh the workspace to start again.</p>
        </section>

        <section className="detail-panel" aria-label="Exception detail">
          {selectedId && !creating && <button className="mobile-back button subtle" onClick={() => { window.location.hash = ''; }} disabled={busy || !!pending}>Back to exceptions</button>}
          {creating && canMutate ? <section className="intake" aria-labelledby="intake-title">
            <p className="eyebrow">Manual intake</p><h2 id="intake-title">New shipment exception</h2>
            <p className="muted">Record an exception for {session.user?.organization_name}. It starts open and unassigned.</p>
            <form onSubmit={createException} aria-label="New exception">
              <label htmlFor="new-reference">Shipment reference</label><input id="new-reference" translate="no" value={createFields.reference} onChange={event => setCreateFields({ ...createFields, reference: event.target.value })} maxLength={80} autoComplete="off" required disabled={locked} aria-describedby="reference-help" />
              <p id="reference-help" className="field-help">References are case-sensitive and must be unique within your organization.</p>
              <label htmlFor="new-summary">Summary</label><input id="new-summary" value={createFields.summary} onChange={event => setCreateFields({ ...createFields, summary: event.target.value })} maxLength={200} required disabled={locked} />
              <label htmlFor="new-details">Exception details</label><textarea id="new-details" rows={6} value={createFields.details} onChange={event => setCreateFields({ ...createFields, details: event.target.value })} maxLength={4000} required disabled={locked} /><span className="character-count">{createFields.details.length} / 4000</span>
              <label htmlFor="new-priority">Priority</label><select id="new-priority" value={createFields.priority} onChange={event => setCreateFields({ ...createFields, priority: event.target.value as CreateFields['priority'] })} disabled={locked}><option value="normal">Normal</option><option value="high">High</option></select>
              <div className="intake-actions"><button className="button primary" type="submit" disabled={locked || !createFields.reference.trim() || !createFields.summary.trim() || !createFields.details.trim()}>Create exception</button><button className="button secondary" type="button" onClick={() => { window.location.hash = ''; }} disabled={busy || !!pending}>Cancel intake</button></div>
            </form>
          </section> : !selectedId ? <div className="empty-detail"><div className="empty-icon" aria-hidden="true">[ ]</div><h2>Choose an exception</h2><p>Open a record to review the details, assign ownership, or document a resolution.</p></div> : detailLoading ? <p className="panel-empty" role="status">Loading record...</p> : !current ? <div className="panel-empty"><h2>Record unavailable</h2><p>Return to the queue or refresh to try again.</p></div> : <>
            {selectedOutsidePage && <p className="queue-selection-note" role="status">This selected record is outside the current queue page or filters. Its details remain open.</p>}
            <div className="detail-heading"><div><p className="reference" translate="no">{current.reference}</p><h2>{current.summary}</h2></div><Status item={current} /></div>
            <div className="record-meta"><span>Version {current.version}</span><span>Updated {dateLabel(current.updated_at)}</span><span className={`priority priority-${current.priority}`}>{current.priority === 'high' ? 'High priority' : 'Normal priority'}</span></div>
            <div className="detail-description"><h3>What needs attention</h3><p>{current.details}</p></div>
            <div className="action-grid"><section className="action-card" aria-labelledby="assignment-title"><p className="eyebrow">Ownership</p><h3 id="assignment-title">{canMutate ? 'Assign a teammate' : 'Current ownership'}</h3><p className="muted">Current owner: <strong>{current.assignee_name ?? 'Unassigned'}</strong></p>{canMutate && <form onSubmit={assign}><label htmlFor="assignee">Assigned to</label><select id="assignee" value={assignment} onChange={event => setAssignment(event.target.value)} disabled={locked || current.status === 'resolved'}><option value="">Unassigned</option>{members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select><button className="button secondary" type="submit" disabled={locked || current.status === 'resolved' || assignment === (current.assignee_id ?? '')}>Save assignment</button></form>}</section>
              <section className="action-card" aria-labelledby="resolution-title"><p className="eyebrow">Outcome</p><h3 id="resolution-title">{current.status === 'resolved' ? 'Resolution recorded' : canMutate ? 'Resolve exception' : 'Resolution'}</h3>{current.status === 'resolved' ? <><p className="resolution-text">{current.resolution}</p><p className="muted small-print">This record is resolved. Its history remains available below.</p></> : canMutate ? <form onSubmit={resolve}><label htmlFor="resolution">Resolution note</label><textarea id="resolution" rows={4} placeholder="Describe what changed and the next handoff." value={resolution} onChange={event => setResolution(event.target.value)} maxLength={2000} required disabled={locked} /><span className="character-count">{resolution.length} / 2000</span><button className="button primary" type="submit" disabled={locked || !resolution.trim()}>Confirm resolution</button></form> : <p className="muted">Only operators can record a resolution.</p>}</section>
            </div>
            <section className="history" aria-labelledby="history-title">
              <div className="history-heading"><h3 id="history-title">Change history</h3><span aria-live="polite">{historyLoading ? `Loading page ${(historyView?.index ?? 0) + 1}` : historyError ? 'Page unavailable' : `${events.length} on this page / Page ${(historyView?.index ?? 0) + 1}`}</span></div>
              {historyError ? <div className="history-error" role="alert"><p>{historyError}</p><div><button className="button secondary" type="button" onClick={() => { if (historyRef.current) void browseHistory(historyRef.current); }} disabled={busy || !!pending || historyLoading || !historyView}>Retry history page</button><button className="button secondary" type="button" onClick={() => void refreshCurrent()} disabled={busy || !!pending}>Refresh latest changes</button></div></div> : historyLoading ? <p className="muted" role="status">Loading change history...</p> : events.length === 0 ? <p className="muted">No changes recorded on this page. Seeded records may start without an earlier event.</p> : <ol className="history-list">{events.map(event => <li key={event.id}><span className="history-dot" aria-hidden="true" /><div><p><strong>{event.actor_name}</strong> {event.action === 'created' ? 'created the exception' : event.action === 'resolved' ? 'resolved the exception' : event.assignee_name ? `assigned ${event.assignee_name}` : 'removed the assignment'}</p>{event.note && <p className="history-note">{event.note}</p>}<p className="history-meta">Version {event.version} / {dateLabel(event.created_at)}</p></div></li>)}</ol>}
              <nav className="history-pages" aria-label="Change history pages"><button className="button secondary" type="button" onClick={newerChanges} disabled={busy || !!pending || historyLoading || !historyView || historyView.index === 0}>Newer changes</button><span>Page {(historyView?.index ?? 0) + 1}</span><button className="button secondary" type="button" onClick={olderChanges} disabled={busy || !!pending || historyLoading || !!historyError || !historyPage?.next_cursor}>Older changes</button></nav>
              <p className="history-boundary">Browsing changes through version {historyView?.throughVersion ?? current.version}. Refresh the workspace to include newer changes. Each page lists its changes from oldest to newest.</p>
            </section>
          </>}
        </section>
      </div>
    </main>}
    <footer className="app-footer"><span>Shipment Exception Workspace</span><span>Synthetic data / Local demonstration</span><a href="/third-party-notices" target="_blank" rel="noreferrer">Dependency notices</a></footer>
  </>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
