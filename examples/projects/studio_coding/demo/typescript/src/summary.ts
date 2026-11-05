import { formatName } from "./format.ts";

export function summarize(names: string[]): string {
  return names.map(formatName).join(", ");
}
