import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";

interface BoardAlertProps {
  message: string;
  /** What each button does here, so several alerts on screen do not all read "Retry". */
  retryLabel: string;
  dismissLabel: string;
  onRetry(): void;
  onDismiss(): void;
}

/** Something the board tried did not happen: what, with a way to try again or let it go. */
export function BoardAlert({ message, retryLabel, dismissLabel, onRetry, onDismiss }: BoardAlertProps) {
  return (
    <div role="alert" className="mx-8 mt-4 flex animate-bt-in items-center gap-3 rounded-bt border border-line bg-danger-soft py-2 pr-2 pl-3.5 text-[12.5px] text-fg max-md:mx-4">
      <p className="m-0 min-w-0 flex-1">{message}</p>
      <Button variant="ghost" aria-label={retryLabel} onClick={onRetry} className="border border-line bg-card text-fg-2">
        Retry
      </Button>
      <IconButton icon={X} label={dismissLabel} title="Dismiss" onClick={onDismiss} />
    </div>
  );
}
