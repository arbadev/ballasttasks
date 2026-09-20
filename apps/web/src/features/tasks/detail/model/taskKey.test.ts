import { describe, expect, it } from "vitest";
import { taskKey } from "./taskKey";

describe("taskKey", () => {
  it("pads the number to two digits behind the BT prefix, as the design does", () => {
    expect(taskKey("t4")).toBe("BT-04");
    expect(taskKey("t16")).toBe("BT-16");
    expect(taskKey("t101")).toBe("BT-101");
  });
});
