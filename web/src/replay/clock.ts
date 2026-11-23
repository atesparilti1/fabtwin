import { useSyncExternalStore } from 'react';

/**
 * Global replay clock. Scenes read `clock.t` directly inside useFrame (no React
 * state per frame); UI subscribes through `useClock`, which is notified at most
 * ~12 times per second while playing and immediately on seeks.
 */
export const SPEEDS = [1, 10, 60, 300, 1000] as const;

interface Snapshot {
  t: number;
  playing: boolean;
  speed: number;
  t0: number;
  t1: number;
}

class Clock {
  t = 0;
  t0 = 0;
  t1 = 1;
  playing = false;
  speed = 300;
  private snap: Snapshot = { t: 0, playing: false, speed: 300, t0: 0, t1: 1 };
  private listeners = new Set<() => void>();
  private raf = 0;
  private last = 0;
  private lastEmit = 0;

  setRange(t0: number, t1: number) {
    if (this.t0 === t0 && this.t1 === t1) return;
    this.t0 = t0;
    this.t1 = t1;
    if (this.t < t0 || this.t > t1) this.t = t0;
    this.emit();
  }

  seek(t: number) {
    this.t = Math.min(this.t1, Math.max(this.t0, t));
    this.emit();
  }

  step(dh: number) {
    this.seek(this.t + dh);
  }

  setSpeed(s: number) {
    this.speed = s;
    this.emit();
  }

  play() {
    if (this.playing) return;
    if (this.t >= this.t1 - 1e-6) this.t = this.t0;
    this.playing = true;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.loop);
    this.emit();
  }

  pause() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.emit();
  }

  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }

  private loop = (now: number) => {
    if (!this.playing) return;
    const dt = Math.min(0.1, (now - this.last) / 1000); // clamp tab-switch jumps
    this.last = now;
    // 1x = one simulated second per real second; t is in hours
    this.t += (dt * this.speed) / 3600;
    if (this.t >= this.t1) {
      this.t = this.t1;
      this.playing = false;
      this.emit();
      return;
    }
    if (now - this.lastEmit > 80) this.emit();
    this.raf = requestAnimationFrame(this.loop);
  };

  private emit() {
    this.lastEmit = performance.now();
    this.snap = { t: this.t, playing: this.playing, speed: this.speed, t0: this.t0, t1: this.t1 };
    this.listeners.forEach((l) => l());
  }

  subscribe = (l: () => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };

  getSnapshot = () => this.snap;
}

export const clock = new Clock();

export function useClock(): Snapshot {
  return useSyncExternalStore(clock.subscribe, clock.getSnapshot);
}
