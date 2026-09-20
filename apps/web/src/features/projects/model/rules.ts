import type { Project, ProjectTone } from "@/features/tasks/model/types";
import type { ProjectFieldErrors } from "@/features/tasks/services/types";

export const NAME_MIN = 2;
export const NAME_MAX = 40;
export const KEY_MIN = 2;
export const KEY_MAX = 4;

/** The colours a new project can take: design tokens only, in the order they are offered. */
export const PROJECT_TONES: readonly ProjectTone[] = ["accent", "info", "ok", "warn", "muted"];

const ALPHABET = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
const KEY_FORMAT = new RegExp(`^[A-Z]{${KEY_MIN},${KEY_MAX}}$`);

/** The name as it is stored and compared: trimmed, with inner runs of whitespace collapsed. */
export function normalizeName(name: string): string {
  return name.trim().replace(/\s+/g, " ");
}

/** What the key input keeps of what is typed: letters, uppercased, up to the maximum length. */
export function cleanKey(input: string): string {
  return lettersOf(input).slice(0, KEY_MAX);
}

/** Every rule a new project must pass; an empty result means the draft is valid. */
export function validateProject(draft: { name: string; key: string }, existing: readonly Project[]): ProjectFieldErrors {
  const errors: ProjectFieldErrors = {};
  const nameError = validateProjectName(draft.name, existing);
  if (nameError) errors.name = nameError;

  const sameKey = existing.find((p) => p.key === draft.key);
  if (!KEY_FORMAT.test(draft.key)) errors.key = `Use ${KEY_MIN} to ${KEY_MAX} letters.`;
  else if (sameKey) errors.key = `The key ${draft.key} is already used by ${sameKey.name}.`;

  return errors;
}

/** The same name rules apply to creation and editing; editing excludes itself. */
export function validateProjectName(input: string, existing: readonly Project[]): string | undefined {
  const errors: ProjectFieldErrors = {};
  const name = normalizeName(input);
  const sameName = existing.find((p) => normalizeName(p.name).toLowerCase() === name.toLowerCase());
  if (name.length === 0) errors.name = "Give the project a name.";
  else if (name.length < NAME_MIN) errors.name = `Use at least ${NAME_MIN} characters.`;
  else if (name.length > NAME_MAX) errors.name = `Keep the name to ${NAME_MAX} characters or fewer.`;
  else if (sameName) errors.name = `A project named "${sameName.name}" already exists.`;

  return errors.name;
}

/**
 * A free key for the name: the initials of several words, or the first three letters of one.
 * Empty until the name has two letters. When the first choice is taken it tries the name's
 * other letters, then the alphabet, so the suggestion is always valid and unused.
 */
export function suggestKey(name: string, taken: readonly string[]): string {
  const words = name.split(/\s+/).map(lettersOf).filter(Boolean);
  const letters = words.join("");
  if (letters.length < KEY_MIN) return "";

  const base = words.length > 1 ? words.map((w) => w[0]).join("").slice(0, KEY_MAX) : letters.slice(0, 3);
  const stem = letters.slice(0, 2);
  const candidates = [
    base,
    ...[...letters.slice(2)].map((letter) => stem + letter),
    ...ALPHABET.map((letter) => stem + letter),
    ...ALPHABET.flatMap((third) => ALPHABET.map((fourth) => stem + third + fourth)),
  ];
  return candidates.find((key) => !taken.includes(key)) ?? "";
}

/** The palette colour the fewest projects use, so a new project is easy to tell apart. */
export function suggestTone(existing: readonly Project[]): ProjectTone {
  const uses = (tone: ProjectTone) => existing.filter((p) => p.tone === tone).length;
  return PROJECT_TONES.reduce((best, tone) => (uses(tone) < uses(best) ? tone : best));
}

/** Uppercase A to Z only: accents are folded to their base letter, everything else dropped. */
function lettersOf(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[^A-Za-z]/g, "")
    .toUpperCase();
}
