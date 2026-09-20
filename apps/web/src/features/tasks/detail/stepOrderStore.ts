/** Session-owned ordering state: failures survive panel close; recovery is always a read. */
export class StepOrderStore {
  private states = new Map<string, "idle" | "pending" | "failed">();
  private listeners = new Set<() => void>();
  get = (taskId: string) => this.states.get(taskId) ?? "idle";
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private set(taskId: string, value: "idle" | "pending" | "failed") {
    this.states.set(taskId, value);
    this.listeners.forEach((listener) => listener());
  }
  run(taskId: string, action: () => Promise<unknown>, recovery = false): void {
    const state = this.get(taskId);
    if (state === "pending" || (state === "failed" && !recovery)) return;
    this.set(taskId, "pending");
    void action().then(() => this.set(taskId, "idle"), () => this.set(taskId, "failed"));
  }
}
