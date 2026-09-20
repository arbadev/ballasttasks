export interface FieldOptions<T> {
  saved: T;
  /** `note` is what the caller has to say about this particular write, if anything. */
  save(value: T, note?: string): Promise<unknown>;
  savable?(value: T): boolean;
}

/** A value on its way to the service, with whatever the writer asked to be recorded about it. */
interface Write<T> {
  value: T;
  note?: string;
}

interface View<T> {
  draft: { value: T } | null;
  failed: Write<T> | null;
}

/**
 * The field's existing debounce/serialized-save machine, with its recovery and draft in the
 * same owner. A mounted control subscribes; disposing that control does not dispose a save.
 *
 * A save releases only the draft it was made from, never a newer one that happens to read the
 * same. Writes run one at a time, newest queued value wins, and failure is shown until this
 * field sends another value of its own - typing alone does not answer it - or the stored value
 * moves without this field asking. Unsavable typing never writes; flush restores the confirmed
 * value, while store explicitly authorizes values such as null and carries the writer's note.
 */
export class AutosaveMachine<T> {
  private view: View<T> = { draft: null, failed: null };
  private readonly listeners = new Set<() => void>();
  private pending: { value: T; timer: ReturnType<typeof setTimeout> | null } | null = null;
  private inFlight: { ticket: number } | null = null;
  private queued: Write<T> | null = null;
  private tickets = 0;
  private options: FieldOptions<T>;

  constructor(options: FieldOptions<T>) {
    this.options = options;
  }

  configure(options: FieldOptions<T>) {
    const before = this.options.saved;
    this.options = options;
    // The stored value moved without this field asking for it - something else wrote the task
    // while no control was mounted. That answers the field's own outstanding failure: its
    // recovery is about a value the reader has since moved past, and retrying it would undo
    // the newer one. What this field stored itself is not such a move; `answered` records it.
    if (this.view.failed && !Object.is(options.saved, before)) this.publish(this.view.draft, null);
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

  private start(write: Write<T>) {
    const ticket = ++this.tickets;
    // Remember the draft at dispatch. A queued write may start after another edit was typed,
    // so matching this reference alone does not authorize releasing a still-pending draft.
    const from = this.view.draft;
    this.inFlight = { ticket };
    const answered = (ok: boolean) => {
      if (this.inFlight?.ticket !== ticket) return;
      this.inFlight = null;
      if (ok) this.options = { ...this.options, saved: write.value };
      const next = this.queued;
      this.queued = null;
      // Only a write already on its way supersedes this answer. A typed edit still waiting for
      // its debounce may be emptied or abandoned before it is ever sent, so letting it count
      // would swallow this refusal and the change would vanish with nothing said.
      const final = !next;
      // A pending edit does not hide a refusal, but only normal settling releases the draft.
      const draft = final && !this.pending && this.view.draft === from ? null : this.view.draft;
      const failed = ok ? null : final ? write : this.view.failed;
      this.publish(draft, failed);
      if (next) this.start(next);
    };
    this.options.save(write.value, write.note).then(() => answered(true), () => answered(false));
  }

  private enqueue(write: Write<T>) {
    const stored = !this.inFlight && !this.queued && write.note === undefined && Object.is(write.value, this.options.saved);
    // A value going to the service is what answers a refusal, not a keystroke that may still be
    // retyped into nothing, and not settling back on the value the task already holds.
    this.publish(stored && this.view.draft && Object.is(this.view.draft.value, write.value) ? null : this.view.draft, stored ? this.view.failed : null);
    if (stored) return;
    if (this.inFlight) this.queued = write;
    else this.start(write);
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
    this.enqueue({ value: edit.value });
    return true;
  };

  /** Explicit value, never inferred from incomplete typing. Shares the ordinary save queue. */
  store = (value: T, note?: string) => {
    if (this.pending?.timer) clearTimeout(this.pending.timer);
    this.pending = null;
    this.publish({ value }, this.view.failed);
    this.enqueue({ value, note });
  };

  flush = () => {
    if (this.commit()) return;
    this.pending = null;
    this.publish(null, this.view.failed);
  };

  change(value: T, delay: number) {
    if (this.pending?.timer) clearTimeout(this.pending.timer);
    this.publish({ value }, this.view.failed);
    this.pending = { value, timer: delay > 0 ? setTimeout(this.commit, delay) : null };
    if (delay === 0) this.commit();
  }

  retry = () => {
    if (this.view.failed) this.store(this.view.failed.value, this.view.failed.note);
  };
}
