export type ClassValue = string | false | null | undefined;

/** Minimal class-name joiner (the `cn()` shadcn components expect). */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
