"""Split one long edit into episodes that each fit a file-size limit, using as few episodes as the quality floor
allows. Cuts land on the points where dead air was removed (never mid-sentence when avoidable). Each episode keeps
the same outro clip(s) and gets its own intro clip."""
import math
from dataclasses import dataclass

from core.encode import AUDIO_KBPS, CONTAINER_OVERHEAD, MIN_CAPPED_KBPS, QUALITY_KBPS, SOURCE_SHARE

BUDGET_SHARE = 0.92   # aim below the limit: the encoder's real size wanders a few percent around its target
FLOOR_SHARE = 0.7     # never plan a bitrate below this share of the source's, so the picture stays clear
SNAP_WINDOW = 0.04    # a cut may move this share of an episode earlier to land on a dead-air cut
MIN_CONTENT_S = 30.0


@dataclass
class Episode:
    index: int  # 1-based
    start: float  # edited time on the main timeline
    end: float
    intro_clip_id: str | None
    video_kbps: int  # cap handed to the encoder (constant-quality mode stays below it on easy footage)
    est_bytes: int  # upper bound

    @property
    def duration(self) -> float:
        return self.end - self.start


def quality_range(preset: str, source_kbps: float | None) -> tuple[int, int]:
    """(floor, cap) in video kbps."""
    cap = QUALITY_KBPS.get(preset, QUALITY_KBPS["tiktok"])["high"]
    if source_kbps:
        cap = min(cap, max(MIN_CAPPED_KBPS, round(source_kbps * SOURCE_SHARE["high"])))
        floor = max(MIN_CAPPED_KBPS, round(source_kbps * FLOOR_SHARE))
    else:
        floor = round(cap * 0.4)
    return min(floor, cap), cap


def plan_episodes(boundaries: list[float], start: float, end: float, *, max_bytes: float, source_kbps: float | None,
                  preset: str, container: str = "mp4", intros: list[tuple[str, float]] | None = None,
                  outro_dur: float = 0.0) -> list[Episode]:
    """`intros` = (clip id, seconds) per intro clip, in order. Raises ValueError("episode_limit_too_small")."""
    intros = intros or []
    audio = AUDIO_KBPS.get(container, 160)
    floor, cap = quality_range(preset, source_kbps)
    budget = max_bytes * BUDGET_SHARE / CONTAINER_OVERHEAD * 8 / 1000  # kilobits per episode, container included
    max_extras = max((d for _, d in intros), default=0.0) + outro_dur
    max_content = budget / (floor + audio) - max_extras
    total = end - start
    if total <= 0 or max_content < MIN_CONTENT_S:
        raise ValueError("episode_limit_too_small")
    n = max(1, math.ceil(total / (max_content * (1 - SNAP_WINDOW))))
    cuts = [start]
    for i in range(1, n):
        ideal = start + total * i / n
        lo = max(ideal - SNAP_WINDOW * total / n, cuts[-1] + MIN_CONTENT_S)
        near = [b for b in boundaries if lo <= b <= ideal]
        cuts.append(max(near) if near else ideal)
    cuts.append(end)
    out = []
    for i in range(n):
        intro_id, intro_d = (intros[min(i, len(intros) - 1)] if intros else (None, 0.0))
        dur = cuts[i + 1] - cuts[i] + intro_d + outro_dur
        kbps = int(min(cap, budget / dur - audio))
        est = round((kbps + audio) * 1000 / 8 * dur * CONTAINER_OVERHEAD)
        out.append(Episode(i + 1, cuts[i], cuts[i + 1], intro_id, kbps, est))
    return out
