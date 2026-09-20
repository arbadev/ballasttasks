export interface FieldOptions<T> {
  saved: T;
  save(value: T): Promise<unknown>;
  savable?(value: T): boolean;
}

interface View<T> {
  draft: { value: T } | null;
  failed: { value: T } | null;
}

/**
 * The field's existing debounce/serialized-save machine, with its recovery and draft in the
 * same owner. A mounted control subscribes; disposing that control does not dispose a save.
 *
 * Only matching answers release a draft. Writes run one at a time, newest queued value wins,
 * and failure is shown only when no newer edit supersedes it. Unsavable typing never writes;
 * flush restores the confirmed value, while store explicitly authorizes values such as null.
 */
export class AutosaveMachine<T> {
  private view: View<T> = { draft: null, failed: null };
  private readonly listeners = new Set<() => void>();
  private pending: { value: T; timer: ReturnType<typeof setTimeout> | null } | null = null;
  private inFlight: { ticket: number; value: T } | null = null;
  private queued: { value: T } | null = null;
  private tickets = 0;
  private options: FieldOptions<T>;

  constructor(options: FieldOptions<T>) {
    this.options = options;
  }

  configure(options: FieldOptions<T>) {
    this.options = options;
  }

  getSnapshot = () => this.view;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private publish(draft: View<T>["draft"], failed: View<T>["failed"]) {
    if (draft === this.view.draft && failed === this.view.failed) return;
    this.view = { draft, failed };
    this.listeners.forEach((listener) => listener());
  }

  private start(value: T) {
    const ticket = ++this.tickets;
    this.inFlight = { ticket, value };
    const answered = (ok: boolean) => {
      if (this.inFlight?.ticket !== ticket) return;
      this.inFlight = null;
      const next = this.queued;
      this.queued = null;
      const final = !next && !this.pending;
      const draft = final && this.view.draft && Object.is(this.view.draft.value, value) ? null : this.view.draft;
      const failed = ok ? null : final ? { value } : this.view.failed;
      this.publish(draft, failed);
      if (next) this.start(next.value);
    };
    this.options.save(value).then(() => answered(true), () => answered(false));
  }

  private enqueue(value: T) {
    if (!this.inFlight && !this.queued && Object.is(value, this.options.saved)) {
      this.publish(this.view.draft && Object.is(this.view.draft.value, value) ? null : this.view.draft, this.view.failed);
      return;
    }
    if (this.inFlight) this.queued = { value };
    else this.start(value);
  }

  private commit = () => {
    const edit = this.pending;
    if (!edit) return true;
    if (edit.timer) clearTimeout(edit.timer);
    if (this.options.savable?.(edit.value) === false) {
      this.pending = { value: edit.value, timer: null };
      return false;
    }
    this.pending = null;
    this.enqueue(edit.value);
    return true;
  };

  /** Explicit value, never inferred from incomplete typing. Shares the ordinary save queue. */
  store = (value: T) => {
    if (this.pending?.timer) clearTimeout(this.pending.timer);
    this.pending = null;
    this.publish({ value }, null);
    this.enqueue(value);
  };

  flush = () => {
    if (this.commit()) return;
    this.pending = null;
    this.publish(null, this.view.failed);
  };

  change(value: T, delay: number) {
    if (this.pending?.timer) clearTimeout(this.pending.timer);
    this.publish({ value }, null);
    this.pending = { value, timer: delay > 0 ? setTimeout(this.commit, delay) : null };
    if (delay === 0) this.commit();
  }

  retry = () => {
    if (this.view.failed) this.store(this.view.failed.value);
  };
}
