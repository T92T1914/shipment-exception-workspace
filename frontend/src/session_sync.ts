// A per-document consistency marker. It never authenticates a request and is
// never persisted or sent through the cross-tab channel.
let context: string | null = null;
let epoch = 0;

export class StaleSessionResponse extends Error {}

export function captureSessionContext() {
  return { context, epoch };
}

export function matchesSessionContext(snapshot: ReturnType<typeof captureSessionContext>) {
  return snapshot.epoch === epoch && snapshot.context === context;
}

export function adoptSessionContext(value: string) {
  if (!/^[0-9a-f]{64}$/.test(value)) throw new Error('The current session could not be confirmed.');
  if (context !== value) epoch++;
  context = value;
}

export function retireSessionContext() {
  epoch++;
  context = null;
}

export function openSessionChannel(changed: () => void) {
  let channel: BroadcastChannel | null = null;
  try {
    channel = new BroadcastChannel('shipment-workspace-session-v1');
    channel.addEventListener('message', event => {
      const value = event.data;
      if (value && typeof value === 'object' && !Array.isArray(value) &&
          Object.keys(value).length === 2 && value.v === 1 && value.type === 'session-changed') changed();
    });
  } catch { /* Request context checks and explicit refresh remain available. */ }
  return {
    notify() {
      try { channel?.postMessage({ v: 1, type: 'session-changed' }); }
      catch { /* A notification failure cannot change the saved auth outcome. */ }
    },
    close() {
      try { channel?.close(); } catch { /* Cleanup has no authority over auth. */ }
      channel = null;
    },
  };
}
