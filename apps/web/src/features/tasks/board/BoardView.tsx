"use client";

/**
 * PLACEHOLDER, owned by the board-view worker. The real board reads
 * `useVisibleTasks({ applyStatus: false })` and moves tasks with `useTaskCommands().move`.
 */
export function BoardView() {
  return (
    <section aria-label="Board" className="flex-1 px-8 py-6 text-[13px] text-fg-3 max-md:px-4">
      The board view goes here.
    </section>
  );
}
