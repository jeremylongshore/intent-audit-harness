export function decisions(x: number, obj?: { value?: number }) {
  let y = 0;
  if (x) y++;
  for (let i = 0; i < x; i++) y++;
  for (const key in { x }) y += key.length;
  for (const value of [x]) y += value;
  while (y < 2) y++;
  do { y--; } while (y > 10);
  try { y += x; } catch { y = 0; }
  switch (x) { case 0: y++; break; case 1: y--; break; default: y = 0; }
  y = x ? y : 0;
  y = (x && y) || 0;
  y = obj?.value ?? y;
  y &&= x;
  y ||= x;
  y ??= x;
  function nested() { return x ? 1 : 0; }
  return y + nested();
}
export const expression = function (x: boolean) { return x ? 1 : 2; };
export const object = { method() { return 1; } };
