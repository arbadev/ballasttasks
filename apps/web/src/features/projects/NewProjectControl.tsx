"use client";

import { Plus } from "lucide-react";
import { useRef, useState } from "react";
import { IconButton } from "@/components/ui/IconButton";
import { NewProjectDialog } from "./NewProjectDialog";

interface NewProjectControlProps {
  /** Called once a project exists, so the sidebar drawer can close and show it. */
  onCreated?: () => void;
  className?: string;
}

/** The plus in the sidebar's Projects heading, and the dialog it opens. */
export function NewProjectControl({ onCreated, className }: NewProjectControlProps) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <IconButton icon={Plus} label="New project" aria-haspopup="dialog" buttonRef={button} onClick={() => setOpen(true)} className={className} />
      {open && (
        <NewProjectDialog
          opener={button}
          onClose={() => setOpen(false)}
          onCreated={() => {
            setOpen(false);
            onCreated?.();
          }}
        />
      )}
    </>
  );
}
