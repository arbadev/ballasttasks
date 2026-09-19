"use client";

import { useVisibleTasks, useWorkspace } from "../workspace/WorkspaceProvider";

/**
 * PLACEHOLDER, owned by the list-view worker. It renders the filtered, sorted titles so the
 * shell's filters are testable; the real rows and quick-add replace everything in here.
 */
export function ListView() {
  const tasks = useVisibleTasks();
  const { actions } = useWorkspace();

  if (tasks.length === 0) {
    return <div className="px-6 py-14 text-[13px] text-fg-3 max-md:px-4">No tasks match these filters.</div>;
  }

  return (
    <ul aria-label="Tasks" className="m-0 flex list-none flex-col p-0">
      {tasks.map((task) => (
        <li key={task.id} className="border-b border-line">
          <button
            type="button"
            onClick={() => actions.selectTask(task.id)}
            className="w-full cursor-pointer truncate px-6 py-[11px] text-left text-sm font-medium transition-colors duration-[160ms] ease-bt hover:bg-card max-md:px-4"
          >
            {task.title}
          </button>
        </li>
      ))}
    </ul>
  );
}
