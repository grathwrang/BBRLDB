# schedule_engine.py
import random
import unicodedata
from collections import defaultdict
from typing import Dict, Optional, List, Set, Tuple, Iterable

from elo import DEFAULT_RATING  # only used if you want to weight by ratings; not required

try:
    # Fallback allows generate() to be called with db_by_class explicitly in tests/scripts
    from storage import load_all as _load_all_dbs
except Exception:
    _load_all_dbs = None


# How many intervening matches must pass before a robot can fight again (per whole schedule).
# 1 means "no back-to-back".
DEFAULT_COOLDOWN_MATCHES = 1


def _normalize(name: Optional[str]) -> str:
    if not name:
        return ""
    return unicodedata.normalize("NFKC", str(name)).strip()


def _canonicalize(name: Optional[str], roster: Iterable[str]) -> str:
    """Return the canonical roster spelling for 'name' (case/Unicode-insensitive) if found, else normalized name."""
    normalized = _normalize(name)
    if not normalized:
        return ""
    if normalized in roster:
        return normalized
    lowered = normalized.casefold()
    for candidate in roster:
        if candidate.casefold() == lowered:
            return candidate
    return normalized


def _collect_present(db_by_class: Dict[str, dict]) -> Dict[str, List[str]]:
    """{weight_class: [robot_name, ...]} for robots marked present and at least 2 per class."""
    out: Dict[str, List[str]] = {}
    for wc, payload in db_by_class.items():
        roster = payload.get("robots") or {}
        contenders = [
            _normalize(n)
            for n, meta in roster.items()
            if meta and meta.get("present")
        ]
        # de-dupe + sort for deterministic behavior
        contenders = sorted({n for n in contenders if n})
        if len(contenders) >= 2:
            out[wc] = contenders
    return out


def _history_counts(db_by_class: Dict[str, dict]) -> Dict[Tuple[str, str, str], int]:
    """
    Count how many times each pair has met historically.
    Key: (weight_class, a, b) where a<b (sorted).
    """
    counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
    for wc, payload in db_by_class.items():
        roster = payload.get("robots") or {}
        canon_names = set(_normalize(n) for n in roster.keys())
        history = payload.get("history") or []
        for m in history:
            a = _canonicalize(m.get("red_corner"), canon_names)
            b = _canonicalize(m.get("white_corner"), canon_names)
            if not a or not b:
                continue
            a, b = sorted((a, b))
            counts[(wc, a, b)] += 1
    return counts


def _all_pairs(robots: List[str]) -> List[Tuple[str, str]]:
    """All unique unordered pairs a<b from a list."""
    pairs: List[Tuple[str, str]] = []
    for i in range(len(robots)):
        for j in range(i + 1, len(robots)):
            a, b = robots[i], robots[j]
            if a and b and a != b:
                pairs.append((a, b) if a < b else (b, a))
    return pairs


def _cooldown_ok(last_seen_idx: Dict[Tuple[str, str], int], wc: str, name: str, next_index: int, cooldown: int) -> bool:
    """Ensure robot 'name' in class 'wc' hasn't fought within the last 'cooldown' matches."""
    idx = last_seen_idx.get((wc, name), -10_000)
    return (next_index - idx) > cooldown


def _choose_next_pair(
    present: Dict[str, List[str]],
    tonight_counts: Dict[Tuple[str, str], int],
    tonight_used_pairs: Set[Tuple[str, str, str]],
    last_seen_idx: Dict[Tuple[str, str], int],
    hist_counts: Dict[Tuple[str, str, str], int],
    desired_per_robot: int,
    next_index: int,
    cooldown: int,
) -> Optional[Tuple[str, str, str]]:
    """
    Build a candidate list across all weight classes, then pick the best.
    Preference:
      1) both robots still need fights (counts < desired_per_robot)
      2) pair not already used tonight
      3) cooldown satisfied for both robots
      4) prefer pairs with hist=0 (never met); otherwise fewer prior meetings
      5) break ties randomly
    """
    candidates: List[Tuple[int, int, float, str, str, str]] = []  # (hist, -need_sum, rand, wc, a, b)

    for wc, robots in present.items():
        # quick per-class need check
        needers = {r for r in robots if tonight_counts[(wc, r)] < desired_per_robot}
        if len(needers) < 2:
            continue

        for a, b in _all_pairs(robots):
            # both still need fights?
            need_a = desired_per_robot - tonight_counts[(wc, a)]
            need_b = desired_per_robot - tonight_counts[(wc, b)]
            if need_a <= 0 or need_b <= 0:
                continue

            key = (wc, a, b)
            if key in tonight_used_pairs:
                continue

            # cooldown
            if not _cooldown_ok(last_seen_idx, wc, a, next_index, cooldown):
                continue
            if not _cooldown_ok(last_seen_idx, wc, b, next_index, cooldown):
                continue

            hist = hist_counts.get(key, 0)
            need_sum = need_a + need_b
            candidates.append((hist, -need_sum, random.random(), wc, a, b))

    if not candidates:
        # If we found nothing with the strict "need both" rule, allow one robot to be at cap
        # (this helps finish schedules when an odd robot remains).
        for wc, robots in present.items():
            for a, b in _all_pairs(robots):
                key = (wc, a, b)
                if key in tonight_used_pairs:
                    continue
                if not _cooldown_ok(last_seen_idx, wc, a, next_index, cooldown):
                    continue
                if not _cooldown_ok(last_seen_idx, wc, b, next_index, cooldown):
                    continue
                # at least one still needs a fight
                need_a = desired_per_robot - tonight_counts[(wc, a)]
                need_b = desired_per_robot - tonight_counts[(wc, b)]
                if max(need_a, need_b) <= 0:
                    continue
                hist = hist_counts.get(key, 0)
                need_sum = max(need_a, 0) + max(need_b, 0)
                candidates.append((hist, -need_sum, random.random(), wc, a, b))

    if not candidates:
        return None

    # Prefer never-met (hist=0), then more overall remaining need, then random
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    _, _, _, wc, a, b = candidates[0]
    return (wc, a, b)


def generate(
    desired_per_robot: int = 1,
    interleave: bool = True,  # kept for API compatibility; cooldown handles spacing
    db_by_class: Optional[Dict[str, dict]] = None,
    seed: Optional[int] = None,
    cooldown_matches: int = DEFAULT_COOLDOWN_MATCHES,
) -> List[Dict[str, str]]:
    """
    Returns a list of {weight_class, red, white} dicts.

    Rules enforced:
      - only present robots are scheduled
      - avoid historical rematches when possible
      - never schedule same pair twice in one night
      - no robot fights back-to-back (configurable via cooldown_matches)
      - try to give each robot up to desired_per_robot fights
    """
    del interleave  # handled implicitly by cooldown
    if seed is not None:
        random.seed(seed)

    if db_by_class is None:
        if _load_all_dbs is None:
            raise RuntimeError("Database loader unavailable; provide db_by_class explicitly")
        db_by_class = _load_all_dbs()
    if not db_by_class:
        return []

    present = _collect_present(db_by_class)
    if not present:
        return []

    hist_counts = _history_counts(db_by_class)

    # tonight tracking
    tonight_counts: Dict[Tuple[str, str], int] = defaultdict(int)  # (wc, name) -> fights tonight
    last_seen_idx: Dict[Tuple[str, str], int] = {}                 # (wc, name) -> index in schedule
    tonight_used_pairs: Set[Tuple[str, str, str]] = set()          # (wc, a, b) a<b

    schedule: List[Tuple[str, str, str]] = []  # (wc, a, b) a<b

    # While there exists at least one robot that still needs fights, try to place a match
    def someone_needs_fights() -> bool:
        for wc, robots in present.items():
            for r in robots:
                if tonight_counts[(wc, r)] < desired_per_robot:
                    return True
        return False

    # Build greedily
    while someone_needs_fights():
        next_index = len(schedule)
        choice = _choose_next_pair(
            present=present,
            tonight_counts=tonight_counts,
            tonight_used_pairs=tonight_used_pairs,
            last_seen_idx=last_seen_idx,
            hist_counts=hist_counts,
            desired_per_robot=desired_per_robot,
            next_index=next_index,
            cooldown=cooldown_matches,
        )
        if choice is None:
            break

        wc, a, b = choice
        # Randomize corners
        if random.random() < 0.5:
            red, white = a, b
        else:
            red, white = b, a

        schedule.append((wc, a, b))  # store canonical pair
        tonight_used_pairs.add((wc, a, b))
        tonight_counts[(wc, a)] += 1
        tonight_counts[(wc, b)] += 1
        last_seen_idx[(wc, a)] = len(schedule) - 1
        last_seen_idx[(wc, b)] = len(schedule) - 1

    # Build API result
    results: List[Dict[str, str]] = []
    used_out: Set[Tuple[str, str, str]] = set()
    for wc, a, b in schedule:
        if (wc, a, b) in used_out:
            continue
        used_out.add((wc, a, b))
        if random.random() < 0.5:
            red, white = a, b
        else:
            red, white = b, a
        results.append({"weight_class": wc, "red": red, "white": white})

    return results
