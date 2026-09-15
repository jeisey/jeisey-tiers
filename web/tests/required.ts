/**
 * Narrow a value a test has already established must exist.
 *
 * `@typescript-eslint/no-non-null-assertion` is on for tests as well as for source, and
 * rightly: a `!` in a test is a silent `undefined` propagating into an assertion that then
 * passes against nothing. This throws with the name of the thing instead, so a fixture that
 * stopped carrying a state fails where it went missing rather than three lines later.
 */
export function required<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) {
    throw new Error(`expected ${what} to exist`);
  }
  return value;
}
