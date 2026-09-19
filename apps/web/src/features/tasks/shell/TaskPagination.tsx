"use client";

import { Button } from "@/components/ui/Button";
import { useWorkspace } from "../workspace/WorkspaceProvider";

export function TaskPagination() {
  const { state, actions } = useWorkspace();
  const page = state.page;
  if (!page || (page.total <= page.limit && page.offset === 0)) return null;
  const pending = state.load.status !== "ready";
  return <nav aria-label="Task pages" className="mt-auto flex flex-wrap items-center justify-end gap-3 border-t border-line px-6 py-3 text-[12px] text-fg-3 max-md:px-4">
    <span aria-live="polite">{page.total ? page.offset + 1 : 0}–{Math.min(page.offset + page.limit, page.total)} of {page.total}{state.view === "board" ? " across all columns" : ""}</span>
    <Button variant="ghost" disabled={pending || page.offset === 0} onClick={() => actions.setPage(Math.max(0, page.offset - page.limit))}>Previous page</Button>
    <Button variant="ghost" disabled={pending || page.offset + page.limit >= page.total} onClick={() => actions.setPage(page.offset + page.limit)}>Next page</Button>
  </nav>;
}
