import { CircleAlert, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface ListLoadErrorProps {
  message: string;
  onRetry: () => void;
}

/** The list when the tasks could not be loaded: what happened, and one way forward. */
export function ListLoadError({ message, onRetry }: ListLoadErrorProps) {
  return (
    <div role="alert" className="flex animate-bt-in flex-col items-start gap-3.5 px-6 py-14 max-md:px-4">
      <span aria-hidden="true" className="grid size-8 place-items-center rounded-bt bg-danger-soft text-danger">
        <CircleAlert size={16} strokeWidth={2.2} />
      </span>
      <div className="flex flex-col gap-1">
        <p className="m-0 text-sm font-medium text-fg">Could not load the tasks.</p>
        <p className="m-0 text-[13px] text-fg-3">{message}</p>
      </div>
      <Button variant="ghost" icon={RotateCw} onClick={onRetry} className="border border-line bg-card text-fg-2">
        Retry
      </Button>
    </div>
  );
}
