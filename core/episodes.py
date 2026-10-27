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
MIN_CLIP_KBPS = 300   # below this a picture is not worth keeping


@dataclass
class Episode:
    index: int  # 1-based
    start: float  # edited time on the main timeline
    end: float
    intro_clip_id: str | None
    video_kbps: int  # cap handed to the encoder (constant-quality mode stays below it on easy footage)
    est_bytes: int  # expected size (from measured samples when there are any, else the cap: an upper bound)
    max_bytes: int = 0  # the most the encoder is allowed to produce (its bitrate cap over the episode)

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


def clip_video_kbps(max_bytes: float, duration: float, *, source_kbps: float | None, preset: str, container: str = "mp4") -> int:
    """Bitrate cap that keeps ONE clip of `duration` seconds under `max_bytes` (same budget rules as an episode).
    Raises ValueError("clip_limit_too_small") when the picture would have to drop below a watchable bitrate."""
    audio = AUDIO_KBPS.get(container, 160)
    _, cap = quality_range(preset, source_kbps)
    budget = max_bytes * BUDGET_SHARE / CONTAINER_OVERHEAD * 8 / 1000
    kbps = int(min(cap, budget / max(duration, 0.1) - audio))
    if kbps < MIN_CLIP_KBPS:
        raise ValueError("clip_limit_too_small")
    return kbps


def plan_episodes(boundaries: list[float], start: float, end: float, *, max_bytes: float, source_kbps: float | None,
                  preset: str, container: str = "mp4", intros: list[tuple[str, float]] | None = None,
                  outro_dur: float = 0.0, measured_kbps: float | None = None) -> list[Episode]:
    """`intros` = (clip id, seconds) per intro clip, in order. `measured_kbps` = the video bitrate this footage really
    needs at the chosen quality (see core/sizing.py): with it, episodes are as long as that allows, because constant-quality
    encoding of easy footage (a talking head, slides) lands far below the worst-case cap. Either way each episode's
    bitrate cap keeps it under the limit. Raises ValueError("episode_limit_too_small")."""
    intros = intros or []
    audio = AUDIO_KBPS.get(container, 160)
    floor, cap = quality_range(preset, source_kbps)
    budget = max_bytes * BUDGET_SHARE / CONTAINER_OVERHEAD * 8 / 1000  # kilobits per episode, container included
    max_extras = max((d for _, d in intros), default=0.0) + outro_dur
    typical = min(cap, measured_kbps) if measured_kbps else None
    max_content = budget / ((typical if typical is not None else floor) + audio) - max_extras
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
        guard = round((kbps + audio) * 1000 / 8 * dur * CONTAINER_OVERHEAD)
        expect = round((min(typical, kbps) + audio) * 1000 / 8 * dur * CONTAINER_OVERHEAD) if typical is not None else guard
        out.append(Episode(i + 1, cuts[i], cuts[i + 1], intro_id, kbps, expect, guard))
    return out
