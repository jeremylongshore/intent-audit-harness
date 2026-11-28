export interface Shape { read(x: number): number }
export type Fn = (x: number) => number;
export declare function ambient(): void;
export function overloaded(x: number): number;
export function overloaded(x: number) { return x ? 1 : 2; }
export const arrow = (x: number) => x && x > 1 ? 3 : 4;
export class Box {
  constructor(public n: number) { if (n < 0) this.n = 0; }
  read(x: number) { const nested = () => x || this.n; return nested(); }
  get value() { return this.n; }
  set value(n: number) { this.n = n; }
  handler = () => this.n ?? 0;
}
export function outer(x: number) { function inner() { return x ? 1 : 0; } return inner(); }
