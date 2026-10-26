import { api } from "./api.js";

const cache = new Map(); // clipId -> { pps, peaks }
const pending = new Set();

/** Load (once) a clip's waveform at ~10 points per second; calls onReady when it arrives. */
export function ensurePeaks(clip, onReady) {
  if (cache.has(clip.id) || pending.has(clip.id)) return;
  pending.add(clip.id);
  const points = Math.max(100, Math.min(60000, Math.ceil(clip.duration * 10)));
  api("GET", `/api/clips/${clip.id}/waveform?points=${points}`)
    .then((r) => cache.set(clip.id, { pps: points / clip.duration, peaks: r.peaks }))
    .catch(() => cache.set(clip.id, { pps: 1, peaks: [] }))
    .finally(() => (pending.delete(clip.id), onReady()));
}

/** Max peak (0..1) of a clip's audio between two source times. */
export function peakMax(clipId, t0, t1) {
  const e = cache.get(clipId);
  if (!e || !e.peaks.length) return 0;
  const i0 = Math.max(0, Math.floor(t0 * e.pps));
  const i1 = Math.min(e.peaks.length, Math.max(i0 + 1, Math.ceil(t1 * e.pps)));
  let m = 0;
  for (let i = i0; i < i1; i++) if (e.peaks[i] > m) m = e.peaks[i];
  return m;
}

export const hasPeaks = (clipId) => cache.has(clipId);
