import { Plus } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type Ref } from "react";

interface QuickAddProps {
  /** Resolves once the task is saved; a rejection keeps the typed title for another try. */
  onAdd: (title: string) => Promise<unknown>;
  /** ArrowDown leaves the field for the first row. */
  onLeaveDown: () => void;
  inputRef: Ref<HTMLInputElement>;
}

/** The list's first line: type a title, press Enter, keep typing the next one. */
export function QuickAdd({ onAdd, onLeaveDown, inputRef }: QuickAddProps) {
  const [title, setTitle] = useState("");
  const [failed, setFailed] = useState(false);
  const errorId = useId();
  /** Titles being saved: a second Enter on the same one must not create it twice. */
  const saving = useRef(new Set<string>());

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // The Enter that confirms an input-method composition is not a submit.
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter") {
      const trimmed = title.trim();
      if (!trimmed || saving.current.has(trimmed)) return;
      saving.current.add(trimmed);
      setFailed(false);
      onAdd(trimmed)
        .then(
          () => setTitle((current) => (current.trim() === trimmed ? "" : current)),
          () => setFailed(true),
        )
        .finally(() => saving.current.delete(trimmed));
    } else if (e.key === "Escape") {
      setTitle("");
      setFailed(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      onLeaveDown();
    }
  };

  return (
    <div className="border-b border-line">
      <div className="flex items-center gap-[14px] px-6 py-[9px] text-fg-3 max-md:gap-3 max-md:px-4">
        <span aria-hidden="true" className="grid size-[18px] flex-none place-items-center rounded-bt-sm border-[1.5px] border-dashed border-line-2">
          <Plus size={11} strokeWidth={2.5} />
        </span>
        {/* The placeholder is set in --fg-3 (5.29:1) on purpose: the design leaves it at the
            browser default, #757575, which measures 3.90:1 on --bg and fails AA. */}
        <input
          ref={inputRef}
          type="text"
          name="title"
          aria-label="Add a task"
          aria-invalid={failed || undefined}
          aria-describedby={failed ? errorId : undefined}
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            setFailed(false);
          }}
          onKeyDown={onKeyDown}
          placeholder="Add a task and press Enter"
          enterKeyHint="done"
          autoComplete="off"
          className="min-w-0 flex-1 border-0 bg-transparent py-1.5 text-[14px] text-fg placeholder:text-fg-3 placeholder:opacity-100"
        />
      </div>
      {failed && (
        <p id={errorId} role="alert" className="m-0 animate-bt-fade px-6 pb-2.5 pl-14 text-[12.5px] text-danger max-md:px-4 max-md:pl-[46px]">
          Could not add the task. Press Enter to try again.
        </p>
      )}
    </div>
  );
}
