"""Tournament bracket generation and progression helpers."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional


def _next_power_of_two(value: int) -> int:
    size = 1
    while size < max(1, value):
        size <<= 1
    return size


def _create_match(
    match_id: str,
    bracket: str,
    round_number: int,
    red_source: Dict[str, object],
    white_source: Dict[str, object],
) -> Dict[str, object]:
    return {
        "id": match_id,
        "bracket": bracket,
        "round": round_number,
        "sources": {"red": red_source, "white": white_source},
        "result": {"winner": None, "loser": None},
        "targets": {},
    }


def _register_target(
    matches: Dict[str, Dict[str, object]],
    source: Dict[str, object],
    target_match_id: str,
    slot: str,
):
    if source.get("kind") != "match":
        return
    match_id = str(source.get("match"))
    if match_id not in matches:
        return
    result_key = str(source.get("result", "winner"))
    match = matches[match_id]
    targets = match.setdefault("targets", {})
    bucket = targets.setdefault(result_key, [])
    entry = {"match": target_match_id, "slot": slot}
    if entry not in bucket:
        bucket.append(entry)


def seed_bracket(
    robots: Iterable[str],
    *,
    elimination_type: str = "single",
    max_robots: Optional[int] = None,
) -> Dict[str, object]:
    """Seed a bracket for the provided robots.

    ``robots`` may be any iterable. ``max_robots`` restricts how many seeds are
    used. ``elimination_type`` accepts "single" or "double".
    """

    elimination_key = (elimination_type or "").strip().lower()
    if elimination_key not in {"single", "double"}:
        raise ValueError("Unsupported elimination format")

    robots_list = [r for r in robots if r]
    cap = None if max_robots is None else int(max_robots)
    if cap is not None and cap > 0:
        robots_list = robots_list[:cap]
    if len(robots_list) < 2:
        raise ValueError("At least two robots are required to seed a bracket")

    bracket: Dict[str, object] = {
        "format": elimination_key,
        "max_robots": cap,
        "selected": list(robots_list),
        "matches": {},
        "order": {"winners": [], "losers": [], "finals": []},
    }

    size = _next_power_of_two(len(robots_list))
    participants = list(robots_list) + [None] * (size - len(robots_list))
    bracket["participants"] = participants

    if elimination_key == "single":
        _build_single_elimination(bracket)
    else:
        _build_double_elimination(bracket)

    _auto_advance_byes(bracket)
    return bracket


def _build_single_elimination(bracket: Dict[str, object]) -> None:
    participants: List[Optional[str]] = bracket["participants"]  # type: ignore[assignment]
    matches: Dict[str, Dict[str, object]] = bracket["matches"]  # type: ignore[assignment]

    total = len(participants)
    round_number = 1
    match_counter = 1
    current_round_ids: List[str] = []
    for idx in range(0, total, 2):
        match_id = f"W{match_counter}"
        match_counter += 1
        red_source = {"kind": "seed", "index": idx}
        white_source = {"kind": "seed", "index": idx + 1}
        match = _create_match(match_id, "winners", round_number, red_source, white_source)
        matches[match_id] = match
        current_round_ids.append(match_id)
    bracket["order"]["winners"].append(list(current_round_ids))  # type: ignore[index]

    while len(current_round_ids) > 1:
        next_round_ids: List[str] = []
        round_number += 1
        for i in range(0, len(current_round_ids), 2):
            match_id = f"W{match_counter}"
            match_counter += 1
            red_source = {"kind": "match", "match": current_round_ids[i], "result": "winner"}
            white_source = {
                "kind": "match",
                "match": current_round_ids[i + 1],
                "result": "winner",
            }
            match = _create_match(match_id, "winners", round_number, red_source, white_source)
            matches[match_id] = match
            next_round_ids.append(match_id)
            _register_target(matches, red_source, match_id, "red")
            _register_target(matches, white_source, match_id, "white")
        bracket["order"]["winners"].append(list(next_round_ids))  # type: ignore[index]
        current_round_ids = next_round_ids

    bracket["order"]["finals"] = [current_round_ids[-1]] if current_round_ids else []  # type: ignore[index]


def _build_double_elimination(bracket: Dict[str, object]) -> None:
    participants: List[Optional[str]] = bracket["participants"]  # type: ignore[assignment]
    matches: Dict[str, Dict[str, object]] = bracket["matches"]  # type: ignore[assignment]

    total = len(participants)
    round_number = 1
    match_counter = 1
    winners_rounds: List[List[str]] = []
    current_round_ids: List[str] = []
    for idx in range(0, total, 2):
        match_id = f"W{match_counter}"
        match_counter += 1
        red_source = {"kind": "seed", "index": idx}
        white_source = {"kind": "seed", "index": idx + 1}
        match = _create_match(match_id, "winners", round_number, red_source, white_source)
        matches[match_id] = match
        current_round_ids.append(match_id)
    winners_rounds.append(list(current_round_ids))

    while len(current_round_ids) > 1:
        next_round_ids: List[str] = []
        round_number += 1
        for i in range(0, len(current_round_ids), 2):
            match_id = f"W{match_counter}"
            match_counter += 1
            red_source = {"kind": "match", "match": current_round_ids[i], "result": "winner"}
            white_source = {
                "kind": "match",
                "match": current_round_ids[i + 1],
                "result": "winner",
            }
            match = _create_match(match_id, "winners", round_number, red_source, white_source)
            matches[match_id] = match
            next_round_ids.append(match_id)
            _register_target(matches, red_source, match_id, "red")
            _register_target(matches, white_source, match_id, "white")
        winners_rounds.append(list(next_round_ids))
        current_round_ids = next_round_ids

    bracket["order"]["winners"] = [list(r) for r in winners_rounds]  # type: ignore[index]

    losers_rounds: List[List[str]] = []
    carry_over: List[Dict[str, object]] = []
    loser_counter = 1
    for index, win_round in enumerate(winners_rounds):
        loser_sources = [
            {"kind": "match", "match": match_id, "result": "loser"} for match_id in win_round
        ]
        entries = carry_over + loser_sources
        round_match_ids: List[str] = []
        cursor = 0
        while cursor + 1 < len(entries):
            red_source = entries[cursor]
            white_source = entries[cursor + 1]
            match_id = f"L{loser_counter}"
            loser_counter += 1
            match = _create_match(match_id, "losers", index + 1, red_source, white_source)
            matches[match_id] = match
            round_match_ids.append(match_id)
            _register_target(matches, red_source, match_id, "red")
            _register_target(matches, white_source, match_id, "white")
            cursor += 2
        if round_match_ids:
            losers_rounds.append(list(round_match_ids))
        next_carry = [
            {"kind": "match", "match": mid, "result": "winner"} for mid in round_match_ids
        ]
        if cursor < len(entries):
            next_carry.append(entries[cursor])
        carry_over = next_carry

    bracket["order"]["losers"] = [list(r) for r in losers_rounds]  # type: ignore[index]

    finals_sources = carry_over[:1]
    winners_final = winners_rounds[-1][0] if winners_rounds else None
    if winners_final is None:
        raise ValueError("Failed to build winners bracket for double elimination")
    source_winner = {"kind": "match", "match": winners_final, "result": "winner"}
    finals_sources = finals_sources or [{"kind": "match", "match": winners_final, "result": "loser"}]
    final_match_id = "GF1"
    final_match = _create_match(final_match_id, "finals", 1, source_winner, finals_sources[0])
    matches[final_match_id] = final_match
    _register_target(matches, source_winner, final_match_id, "red")
    _register_target(matches, finals_sources[0], final_match_id, "white")
    bracket["order"]["finals"] = [final_match_id]  # type: ignore[index]


def resolve_match_participants(bracket: Dict[str, object], match_id: str) -> Dict[str, Optional[str]]:
    match = bracket["matches"].get(match_id)
    if not match:
        raise KeyError(f"Unknown match: {match_id}")
    participants = {}
    for slot in ("red", "white"):
        source = match["sources"].get(slot)
        participants[slot] = _resolve_source(bracket, source) if source else None
    return participants


def _resolve_source(bracket: Dict[str, object], source: Optional[Dict[str, object]]) -> Optional[str]:
    if not source:
        return None
    kind = source.get("kind")
    if kind == "seed":
        index = int(source.get("index", -1))
        participants: List[Optional[str]] = bracket.get("participants", [])  # type: ignore[assignment]
        if 0 <= index < len(participants):
            return participants[index]
        return None
    if kind == "match":
        match_id = str(source.get("match"))
        result_key = str(source.get("result", "winner"))
        match = bracket["matches"].get(match_id, {})
        result = match.get("result", {})
        return result.get(result_key)
    return None


def record_match_result(
    bracket: Dict[str, object],
    match_id: str,
    winner: str,
    *,
    _auto: bool = False,
) -> Dict[str, object]:
    if not winner:
        raise ValueError("Winner name must be provided")
    matches: Dict[str, Dict[str, object]] = bracket["matches"]  # type: ignore[assignment]
    if match_id not in matches:
        raise KeyError(f"Unknown match: {match_id}")
    match = matches[match_id]
    current_winner = match["result"].get("winner")
    if current_winner:
        if current_winner != winner:
            raise ValueError(f"Match {match_id} already has a different winner recorded")
        return match

    participants = resolve_match_participants(bracket, match_id)
    valid_names = {slot: name for slot, name in participants.items() if name}
    if winner not in valid_names.values():
        raise ValueError(f"Winner {winner} is not scheduled in match {match_id}")

    match["result"]["winner"] = winner
    loser = None
    for slot, name in participants.items():
        if name and name != winner:
            loser = name
            break
    match["result"]["loser"] = loser

    if not _auto:
        _auto_advance_byes(bracket)

    return match


def _auto_advance_byes(bracket: Dict[str, object]) -> None:
    changed = True
    while changed:
        changed = False
        for match_id, match in bracket["matches"].items():
            if match["result"].get("winner"):
                continue
            participants = resolve_match_participants(bracket, match_id)
            sources = match.get("sources", {})
            waiting_on_previous = False
            for slot in ("red", "white"):
                if participants.get(slot) is None:
                    source = sources.get(slot) if isinstance(sources, dict) else None
                    if isinstance(source, dict) and source.get("kind") == "match":
                        waiting_on_previous = True
                        break
            if waiting_on_previous:
                continue
            contenders = [name for name in participants.values() if name]
            if len(contenders) == 1:
                record_match_result(bracket, match_id, contenders[0], _auto=True)
                changed = True


def serialize_bracket(bracket: Optional[Dict[str, object]]) -> Optional[Dict[str, object]]:
    if bracket is None:
        return None
    serialized = {
        "format": bracket.get("format"),
        "max_robots": bracket.get("max_robots"),
        "selected": list(bracket.get("selected", [])),
        "participants": list(bracket.get("participants", [])),
        "order": bracket.get("order", {}),
        "matches": {},
    }
    matches: Dict[str, Dict[str, object]] = bracket.get("matches", {})
    for match_id, match in matches.items():
        participants = resolve_match_participants(bracket, match_id)
        serialized["matches"][match_id] = {
            "id": match_id,
            "bracket": match.get("bracket"),
            "round": match.get("round"),
            "sources": match.get("sources"),
            "targets": match.get("targets", {}),
            "winner": match.get("result", {}).get("winner"),
            "loser": match.get("result", {}).get("loser"),
            "red": participants.get("red"),
            "white": participants.get("white"),
        }
    return serialized

