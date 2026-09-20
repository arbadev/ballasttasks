"use client";

import { useSyncExternalStore } from "react";
import { useDetailSession } from "./DetailSession";

/** A replacement title and its open editor survive remounts under the signed-in session. */
export function useStepRename(taskId: string, stepId: string, send: (text: string) => Promise<unknown>) {
  const { stepRenames: store } = useDetailSession();
  const key = `${taskId}:${stepId}`;
  const read = () => store.get(key);
  const state = useSyncExternalStore(store.subscribe, read, read);
  const run = (text: string, owned: boolean) => {
    store.update(key, (c) => ({ ...c, sending: { text, failed: false, owned } }));
    void send(text).then(
      () => store.update(key, (c) => ({ ...c, text: c.sending?.owned ? "" : c.text, sending: null })),
      () => store.update(key, (c) => ({ ...c, sending: c.sending ? { ...c.sending, failed: true } : null })),
    );
  };
  return {
    ...state,
    sending: state.sending !== null && !state.sending.failed,
    busy: state.sending !== null,
    failed: state.sending?.failed ? state.sending.text : null,
    setText(text: string) {
      store.update(key, (c) => ({ open: true, text, sending: c.sending ? { ...c.sending, owned: false } : null }));
    },
    submit() {
      const c = store.get(key);
      const text = c.text.trim();
      if (c.sending || !text) return;
      store.update(key, (c) => ({ ...c, open: false, text }));
      run(text, true);
    },
    retry() {
      const held = store.get(key).sending;
      if (held?.failed) run(held.text, held.owned);
    },
    dismiss() {
      store.update(key, (c) => c.sending?.failed ? { ...c, sending: null } : c);
    },
    cancel() {
      store.update(key, (c) => c.sending && !c.sending.failed ? c : { open: false, text: "", sending: null });
    },
  };
}
