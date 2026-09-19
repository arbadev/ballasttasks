import { describe, expect, it } from "vitest";
import type { Project } from "@/features/tasks/model/types";
import { PROJECT_TONES, cleanKey, normalizeName, suggestKey, suggestTone, validateProject } from "./rules";

const EXISTING: Project[] = [
  { id: "ballast", name: "Ballast Tasks", key: "BT", tone: "accent" },
  { id: "inbox", name: "Inbox", key: "IN", tone: "muted" },
];

const draft = (over: Partial<{ name: string; key: string }> = {}) => ({ name: "Marketing", key: "MAR", ...over });

describe("normalizeName", () => {
  it("trims and collapses inner whitespace", () => {
    expect(normalizeName("  Release   notes \n")).toBe("Release notes");
  });
});

describe("validateProject: name", () => {
  it("accepts a valid draft", () => {
    expect(validateProject(draft(), EXISTING)).toEqual({});
  });

  it("requires a name, after trimming", () => {
    expect(validateProject(draft({ name: "   " }), EXISTING).name).toBe("Give the project a name.");
  });

  it("needs at least 2 characters", () => {
    expect(validateProject(draft({ name: " a " }), EXISTING).name).toBe("Use at least 2 characters.");
    expect(validateProject(draft({ name: "ab" }), EXISTING).name).toBeUndefined();
  });

  it("allows at most 40 characters, counted after trimming", () => {
    expect(validateProject(draft({ name: "x".repeat(41) }), EXISTING).name).toBe("Keep the name to 40 characters or fewer.");
    expect(validateProject(draft({ name: `  ${"x".repeat(40)}  ` }), EXISTING).name).toBeUndefined();
  });

  it("must be unique, ignoring case and surrounding space", () => {
    expect(validateProject(draft({ name: "  ballast TASKS " }), EXISTING).name).toBe('A project named "Ballast Tasks" already exists.');
  });
});

describe("validateProject: key", () => {
  it.each(["", "A", "ABCDE", "ab", "A1", "A B"])("rejects %j: a key is 2 to 4 uppercase letters", (key) => {
    expect(validateProject(draft({ key }), EXISTING).key).toBe("Use 2 to 4 letters.");
  });

  it.each(["AB", "ABC", "ABCD"])("accepts %s", (key) => {
    expect(validateProject(draft({ key }), EXISTING).key).toBeUndefined();
  });

  it("must be unique, and says who has it", () => {
    expect(validateProject(draft({ key: "BT" }), EXISTING).key).toBe("The key BT is already used by Ballast Tasks.");
  });

  it("reports both fields at once", () => {
    expect(Object.keys(validateProject({ name: "", key: "" }, EXISTING))).toEqual(["name", "key"]);
  });

  it("ignores projects that have no key", () => {
    expect(validateProject(draft(), [{ id: "old", name: "Old", tone: "muted" }])).toEqual({});
  });
});

describe("cleanKey", () => {
  it("keeps letters only, uppercased, up to 4", () => {
    expect(cleanKey("m-k 7t!xyz")).toBe("MKTX");
  });
});

describe("suggestKey", () => {
  it("uses the initials of a name of several words", () => {
    expect(suggestKey("Release notes", [])).toBe("RN");
    expect(suggestKey("One two three four five", [])).toBe("OTTF");
  });

  it("uses the first three letters of a single word", () => {
    expect(suggestKey("Marketing", [])).toBe("MAR");
    expect(suggestKey("  qa ", [])).toBe("QA");
  });

  it("ignores digits, punctuation and accents", () => {
    expect(suggestKey("Área 51: órbita", [])).toBe("AO");
  });

  it("suggests nothing until there are two letters to work with", () => {
    expect(suggestKey("", [])).toBe("");
    expect(suggestKey("M", [])).toBe("");
    expect(suggestKey("42", [])).toBe("");
  });

  it("steps past keys that are taken", () => {
    expect(suggestKey("Big Thing", ["BT"])).toBe("BIG");
    expect(suggestKey("Big Thing", ["BT", "BIG"])).toBe("BIT");
    expect(suggestKey("Marketing", ["MAR"])).toBe("MAK");
  });

  it("always suggests a valid, free key", () => {
    const taken = ["QA", "QAA"];
    const key = suggestKey("qa", taken);
    expect(key).toMatch(/^[A-Z]{2,4}$/);
    expect(taken).not.toContain(key);
  });
});

describe("suggestTone", () => {
  it("offers a small palette of token colours", () => {
    expect(PROJECT_TONES).toEqual(["accent", "info", "ok", "warn", "muted"]);
  });

  it("picks the least used colour, in palette order", () => {
    expect(suggestTone(EXISTING)).toBe("info");
    expect(suggestTone([])).toBe("accent");
    expect(suggestTone([...EXISTING, { id: "p1", name: "One", tone: "info" }])).toBe("ok");
  });
});
