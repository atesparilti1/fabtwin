/// <reference lib="webworker" />
import { simulate, type Rule, type SimInput, type SimParams } from './sim';

export interface WorkerRequest {
  id: number;
  input: SimInput;
  params: Omit<SimParams, 'rule'>;
  rules: Rule[];
}

self.onmessage = (e: MessageEvent<WorkerRequest>) => {
  const { id, input, params, rules } = e.data;
  try {
    for (const rule of rules) {
      const res = simulate(input, { ...params, rule });
      self.postMessage({ id, type: 'result', res });
    }
    self.postMessage({ id, type: 'done' });
  } catch (err) {
    self.postMessage({ id, type: 'error', message: err instanceof Error ? err.message : String(err) });
  }
};
