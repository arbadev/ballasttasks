import { CircleAlert, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface BoardLoadErrorProps {
  /** What went wrong, when the failure said something beyond "it failed". */
  detail?: string;
  onRetry: () => void;
}

/** The board when the tasks could not be loaded: what happened, and one way forward. */
export function BoardLoadError({ detail, onRetry }: BoardLoadErrorProps) {
  return (
    <div role="alert" className="flex animate-bt-in flex-col items-start gap-3.5 px-8 py-14 max-md:px-4">
      <span aria-hidden="true" className="grid size-8 place-items-center rounded-bt bg-danger-soft text-danger">
        <CircleAlert size={16} strokeWidth={2.2} />
      </span>
      <div className="flex flex-col gap-1">
        <p className="m-0 text-sm font-medium text-fg">Could not load the board.</p>
        {detail && <p className="m-0 text-[13px] text-fg-3">{detail}</p>}
      </div>
      <Button variant="ghost" icon={RotateCw} onClick={onRetry} className="border border-line bg-card text-fg-2">
        Retry
      </Button>
    </div>
  );
}
