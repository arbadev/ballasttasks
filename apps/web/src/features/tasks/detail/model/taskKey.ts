/** "t4" -> "BT-04": the design's task key, the id's number padded to two digits. */
export function taskKey(id: string): string {
  return `BT-${id.slice(1).padStart(2, "0")}`;
}
