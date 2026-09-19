import type { Attachment } from "../../model/types";

const FILE_TYPES: Record<string, { kind: "pdf" | "image"; label: string }> = {
  "application/pdf": { kind: "pdf", label: "PDF" },
  "image/png": { kind: "image", label: "PNG" },
  "image/jpeg": { kind: "image", label: "JPG" },
  "image/gif": { kind: "image", label: "GIF" },
  "image/webp": { kind: "image", label: "WEBP" },
};
export const FILE_ACCEPT = Object.keys(FILE_TYPES).join(",");

/** Browser metadata only: validation never reads the file body. Servers must validate bytes. */
export function fileAttachment(file: File): { attachment: Attachment; uploading: Attachment } | { error: string } {
  const type = FILE_TYPES[file.type];
  if (!type) return { error: "Choose a PDF or a PNG, JPG, GIF or WEBP image." };
  if (file.size > 10 * 1024 * 1024) return { error: "Choose a file that is 10 MB or smaller." };
  const size = file.size >= 1024 * 1024 ? `${Number((file.size / (1024 * 1024)).toFixed(1))} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  return {
    attachment: { kind: type.kind, name: file.name, meta: `${type.label} · ${size}` },
    uploading: { kind: type.kind, name: file.name, meta: `${type.label} · uploading…` },
  };
}
