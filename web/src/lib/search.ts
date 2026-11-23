/** Index of the last element with key(a[i]) <= t, or -1. `a` sorted ascending by key. */
export function lastLE<T>(a: ArrayLike<T>, t: number, key: (x: T) => number): number {
  let lo = 0, hi = a.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (key(a[mid]) <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

/** Same for a plain Float64Array of times. */
export function lastLEf(a: Float64Array, t: number, lo = 0, hi = a.length - 1): number {
  let ans = lo - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (a[mid] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}
