/** Per-step title edits are replacements, not acknowledged comment/step appends. */
interface RenameState {
  open: boolean;
  text: string;
  sending: { text: string; failed: boolean; owned: boolean } | null;
}
const EMPTY: RenameState = { open: false, text: "", sending: null };

export class StepRenameStore {
  private state = new Map<string, RenameState>();
  private listeners = new Set<() => void>();
  get = (key: string): RenameState => this.state.get(key) ?? EMPTY;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  update(key: string, change: (state: RenameState) => RenameState): void {
    const before = this.get(key);
    const after = change(before);
    if (after === before) return;
    if (!after.open && after.text === "" && !after.sending) this.state.delete(key);
    else this.state.set(key, after);
    this.listeners.forEach((listener) => listener());
  }
}
