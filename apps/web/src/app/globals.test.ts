import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest runs from the package root (apps/web).
const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");
const compact = css.replace(/\s+/g, "");

// The design's /*SKIN*/ :root block, value for value. Fonts are the one exception: the
// families come from next/font variables instead of a Google Fonts stylesheet.
const SKIN: Record<string, string> = {
  "--bg": "#15171a",
  "--panel": "#191c20",
  "--card": "#1f2328",
  "--card-2": "#272c33",
  "--fg": "#f2f3f4",
  "--fg-2": "#a7adb5",
  "--fg-3": "#858c95",
  "--line": "rgba(255,255,255,.07)",
  "--line-2": "rgba(255,255,255,.13)",
  "--acc": "#c6f432",
  "--acc-fg": "#111418",
  "--acc-soft": "rgba(198,244,50,.12)",
  "--acc-glow": "0001pxrgba(198,244,50,.25),010px30px-10pxrgba(198,244,50,.45)",
  "--danger": "#ff5d5d",
  "--danger-soft": "rgba(255,93,93,.14)",
  "--warn": "#ffb224",
  "--warn-soft": "rgba(255,178,36,.14)",
  "--ok": "#4cd37e",
  "--ok-soft": "rgba(76,211,126,.14)",
  "--info": "#7fb2ff",
  "--info-soft": "rgba(127,178,255,.14)",
  "--backdrop": "rgba(8,9,11,.6)",
  "--r": "4px",
  "--r-sm": "3px",
  "--r-av": "4px",
  "--sh-1": "01px2pxrgba(0,0,0,.4)",
  "--sh-2": "024px80px-20pxrgba(0,0,0,.85),0001pxrgba(255,255,255,.06)",
  "--sh-3": "012px32px-14pxrgba(0,0,0,.9)",
  "--hw": "600",
  "--hls": "-0.01em",
  "--hsize": "22px",
  "--ease": "cubic-bezier(.2,.8,.2,1)",
};

describe("globals.css design tokens", () => {
  it.each(Object.entries(SKIN))("defines %s exactly as the design skin does", (name, value) => {
    expect(compact).toContain(`${name}:${value};`);
  });

  it("builds the three font stacks on the next/font variables", () => {
    expect(compact).toContain("--font:var(--font-dm-sans),system-ui,sans-serif;");
    expect(compact).toContain("--font-h:var(--font-space-grotesk),system-ui,sans-serif;");
    expect(compact).toContain(
      "--mono:var(--font-jetbrains-mono),ui-monospace,SFMono-Regular,monospace;",
    );
  });

  it.each(["bt-in", "bt-fade", "bt-panel", "bt-modal", "bt-pop", "bt-shimmer", "bt-pulse", "bt-blink"])(
    "ports the %s keyframes",
    (name) => {
      expect(css).toMatch(new RegExp(`@keyframes ${name}\\s*\\{`));
    },
  );

  it("maps the tokens into the Tailwind theme so components never use raw hex", () => {
    for (const token of ["bg", "panel", "card", "card-2", "fg", "fg-2", "fg-3", "line", "line-2", "acc", "acc-fg", "acc-soft", "danger", "warn", "ok", "info", "backdrop"]) {
      expect(compact).toContain(`--color-${token}:var(--${token});`);
    }
  });

  it("keeps the design's focus ring, selection colour, scrollbar and reduced-motion rule", () => {
    expect(compact).toContain(":focus-visible{outline:2pxsolidvar(--acc);outline-offset:2px");
    expect(compact).toContain("::selection{background:color-mix(insrgb,var(--acc)35%,transparent)");
    expect(compact).toContain("::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:8px");
    expect(css).toMatch(/@media \(prefers-reduced-motion:\s*reduce\)/);
  });
});
