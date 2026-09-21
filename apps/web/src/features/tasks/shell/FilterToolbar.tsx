"use client";

import { Search } from "lucide-react";
import { useState } from "react";
import { Select } from "@/components/ui/Select";
import { TextInput } from "@/components/ui/TextInput";
import type { DueFilter, PriorityFilter, SortBy, StatusFilter } from "../model/filter";
import { STATUSES } from "../model/statuses";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { MAX_SEARCH_LENGTH } from "../workspace/route";

const STATUS_OPTIONS: readonly { value: StatusFilter; label: string }[] = [
  { value: "open", label: "All open" },
  ...STATUSES.map((s) => ({ value: s.id, label: s.name })),
  { value: "all", label: "Everything" },
];

const DUE_OPTIONS: readonly { value: DueFilter; label: string }[] = [
  { value: "any", label: "Any date" },
  { value: "overdue", label: "Overdue" },
  { value: "today", label: "Today" },
  { value: "week", label: "Next 7 days" },
  { value: "none", label: "No date" },
];

const PRIORITY_OPTIONS: readonly { value: PriorityFilter; label: string }[] = [
  { value: "any", label: "Any" },
  { value: "0", label: "P0" },
  { value: "1", label: "P1" },
  { value: "2", label: "P2" },
  { value: "3", label: "P3" },
];

const SORT_OPTIONS: readonly { value: SortBy; label: string }[] = [
  { value: "urgency", label: "Urgency" },
  { value: "importance", label: "Importance" },
  { value: "due", label: "Due date" },
  { value: "updated", label: "Recently updated" },
];

export function FilterToolbar() {
  const { state, actions } = useWorkspace();
  const { query } = state;

  return (
    <div role="toolbar" aria-label="Filters" className="flex flex-wrap items-center gap-2 border-b border-line px-6 py-2.5 max-md:px-4">
      <Select label="Status" value={query.status} options={STATUS_OPTIONS} onChange={actions.setStatusFilter} />
      <Select label="Due" value={query.due} options={DUE_OPTIONS} onChange={actions.setDueFilter} />
      <Select label="Priority" value={query.priority} options={PRIORITY_OPTIONS} onChange={actions.setPriorityFilter} />
      <Select label="Sort" value={state.sort} options={SORT_OPTIONS} onChange={actions.setSort} />
      <SearchField search={query.search} onSearch={actions.setSearch} />
    </div>
  );
}

/**
 * The route reaches `search` in a transition, so the box shows what was typed until each
 * keystroke's URL comes back; a search that did not come from typing here replaces the draft.
 */
function SearchField({ search, onSearch }: { search: string; onSearch: (search: string) => void }) {
  const [draft, setDraft] = useState({ value: search, typed: [] as string[], seen: search });
  if (draft.seen !== search) {
    const echo = draft.typed.indexOf(search);
    const typed = echo < 0 ? [] : draft.typed.slice(echo + 1);
    setDraft({ value: typed.length ? draft.value : search, typed, seen: search });
  }
  return (
    <TextInput
      type="search"
      label="Search tasks"
      placeholder="Search tasks"
      icon={Search}
      value={draft.value}
      maxLength={MAX_SEARCH_LENGTH}
      onChange={(value) => {
        setDraft((current) => ({ ...current, value, typed: [...current.typed, value] }));
        onSearch(value);
      }}
      className="ml-auto min-w-[220px] max-md:ml-0 max-md:w-full"
    />
  );
}
