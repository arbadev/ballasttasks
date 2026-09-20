import type { Task } from "@/features/tasks/model/types";
import type { Generation, ProposedStep, StepGenerationService, TaskService } from "@/features/tasks/services/types";

/**
 * A StepGenerationService the test moves by hand: `start` goes to running, `propose` lands
 * the draft, `failNextStart` makes the next start reject. It prunes and accepts for real,
 * so the panel can be driven from "Generate steps" to the steps showing up in the task.
 */
export class ScriptedStepGeneration implements StepGenerationService {
  readonly calls: unknown[][] = [];
  private generation: Generation | null = null;
  private failing = false;
  private readonly listeners = new Set<(g: Generation | null) => void>();

  constructor(private readonly tasks: Pick<TaskService, "get">) {}

  failNextStart() {
    this.failing = true;
  }

  propose(texts: string[]) {
    if (!this.generation) throw new Error("Nothing is running.");
    const steps: ProposedStep[] = texts.map((text, i) => ({ id: `p${i + 1}`, text }));
    this.set({ taskId: this.generation.taskId, phase: "proposed", steps });
  }

  async start(taskId: string) {
    this.calls.push(["start", taskId]);
    if (this.failing) {
      this.failing = false;
      throw new Error("The assistant is unreachable.");
    }
    this.set({ taskId, phase: "running" });
  }

  current() {
    return this.generation;
  }

  subscribe(listener: (g: Generation | null) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  removeProposed(stepId: string) {
    this.calls.push(["removeProposed", stepId]);
    const g = this.generation;
    if (g?.phase === "proposed") this.set({ ...g, steps: g.steps.filter((s) => s.id !== stepId) });
  }

  async accept(): Promise<Task | null> {
    this.calls.push(["accept"]);
    const g = this.generation;
    if (g?.phase !== "proposed") return null;
    const task = await this.tasks.get(g.taskId);
    this.set(null);
    return task && { ...task, steps: [...task.steps, ...g.steps.map((s) => ({ ...s, done: false }))] };
  }

  async discard() {
    this.calls.push(["discard"]);
    this.set(null);
  }

  private set(generation: Generation | null) {
    this.generation = generation;
    this.listeners.forEach((l) => l(generation));
  }
}
