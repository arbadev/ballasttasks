import type { Page } from "@playwright/test";

export interface Comparison {
  width: number;
  height: number;
  /** Pixels that differ, including any area only one of the two images covers. */
  differing: number;
  ratio: number;
  sameSize: boolean;
  /** PNG of the differences: matching pixels dimmed, differing ones in red. */
  diff: Buffer;
}

/**
 * How far a colour channel (0-255) may drift before the pixel counts as different. Kept
 * tight on purpose: neighbouring surface tokens (--card, --card-2) are only ~8 apart, so a
 * loose tolerance would let a wrong token through. 2 absorbs rounding noise and nothing else.
 */
export const CHANNEL_TOLERANCE = 2;

/**
 * Compares two PNGs pixel by pixel on a canvas inside the browser, which keeps the harness
 * free of image-processing dependencies. `page` is only a place to run the canvas code.
 */
export async function comparePngs(page: Page, design: Buffer, app: Buffer): Promise<Comparison> {
  const result = await page.evaluate(
    async ({ a, b, tolerance }) => {
      const load = (src: string) =>
        new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error("could not decode screenshot"));
          img.src = src;
        });
      const [imgA, imgB] = await Promise.all([load(a), load(b)]);
      const width = Math.max(imgA.width, imgB.width);
      const height = Math.max(imgA.height, imgB.height);

      const pixels = (img: HTMLImageElement) => {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(img, 0, 0);
        return ctx.getImageData(0, 0, width, height).data;
      };
      const dataA = pixels(imgA);
      const dataB = pixels(imgB);

      const out = document.createElement("canvas");
      out.width = width;
      out.height = height;
      const outCtx = out.getContext("2d")!;
      const diff = outCtx.createImageData(width, height);

      let differing = 0;
      for (let i = 0; i < dataA.length; i += 4) {
        const x = (i / 4) % width;
        const y = Math.floor(i / 4 / width);
        const covered = x < imgA.width && y < imgA.height && x < imgB.width && y < imgB.height;
        const delta = Math.max(Math.abs(dataA[i] - dataB[i]), Math.abs(dataA[i + 1] - dataB[i + 1]), Math.abs(dataA[i + 2] - dataB[i + 2]));
        if (!covered || delta > tolerance) {
          differing++;
          diff.data.set([255, 40, 40, 255], i);
        } else {
          diff.data.set([dataA[i] / 3, dataA[i + 1] / 3, dataA[i + 2] / 3, 255], i);
        }
      }
      outCtx.putImageData(diff, 0, 0);

      return {
        width,
        height,
        differing,
        sameSize: imgA.width === imgB.width && imgA.height === imgB.height,
        diff: out.toDataURL("image/png").split(",")[1],
      };
    },
    { a: `data:image/png;base64,${design.toString("base64")}`, b: `data:image/png;base64,${app.toString("base64")}`, tolerance: CHANNEL_TOLERANCE },
  );

  return { ...result, ratio: result.differing / (result.width * result.height), diff: Buffer.from(result.diff, "base64") };
}
