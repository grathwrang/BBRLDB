import importlib
import importlib.util
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib import parse as urllib_parse
from urllib import request as urllib_request

_REQUESTS_MODULE = None
if importlib.util.find_spec("requests") is not None:
    _REQUESTS_MODULE = importlib.import_module("requests")


class ChallongeService:
    """Fetches and caches Challonge tournament data for public views."""

    API_URL_TEMPLATE = "https://api.challonge.com/v1/tournaments/{tournament}.json"

    def __init__(
        self,
        api_key: Optional[str] = None,
        tournament: Optional[str] = None,
        *,
        session: Optional[Any] = None,
        cache_ttl: int = 15,
    ) -> None:
        self._explicit_api_key = api_key
        self._explicit_tournament = tournament
        if session is not None:
            self._session = session
        elif _REQUESTS_MODULE is not None:
            self._session = _REQUESTS_MODULE.Session()
        else:
            self._session = None
        self._cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cached_payload: Optional[Dict[str, Any]] = None
        self._cached_error: Optional[str] = None
        self._cached_at: float = 0.0

    @property
    def api_key(self) -> Optional[str]:
        return self._explicit_api_key or os.environ.get("CHALLONGE_API_KEY")

    @property
    def tournament(self) -> Optional[str]:
        return self._explicit_tournament or os.environ.get("CHALLONGE_TOURNAMENT")

    def is_configured(self) -> bool:
        return bool(self.api_key and self.tournament)

    def _round_label(self, round_number: Optional[int]) -> str:
        if round_number is None:
            return "Round"
        if round_number > 0:
            return f"Round {round_number}"
        if round_number < 0:
            return f"Losers Round {abs(round_number)}"
        return "Round"

    def _score_text(self, scores_csv: Optional[str]) -> str:
        if not scores_csv:
            return ""
        parts = scores_csv.split("-")
        if len(parts) != 2:
            return scores_csv
        left = parts[0].strip()
        right = parts[1].strip()
        return f"{left} – {right}"

    def _unwrap_collection(self, items: Optional[Any], key: str) -> list:
        results: list = []
        if not items:
            return results
        for item in items:
            if isinstance(item, dict) and key in item:
                results.append(item[key])
            else:
                results.append(item)
        return results

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tournament = payload.get("tournament", payload)
        participants_raw = self._unwrap_collection(tournament.get("participants"), "participant")
        matches_raw = self._unwrap_collection(tournament.get("matches"), "match")

        participants: Dict[int, Dict[str, Any]] = {}
        normalized_participants = []
        for part in participants_raw:
            pid = part.get("id")
            display_name = (
                part.get("display_name")
                or part.get("name")
                or part.get("challonge_username")
                or "TBD"
            )
            entry = {
                "id": pid,
                "name": display_name,
                "seed": part.get("seed"),
                "checked_in": bool(part.get("checked_in_at")),
            }
            normalized_participants.append(entry)
            if pid is not None:
                participants[pid] = entry

        normalized_matches = []
        for match in matches_raw:
            player1_id = match.get("player1_id")
            player2_id = match.get("player2_id")
            winner_id = match.get("winner_id")
            entry = {
                "id": match.get("id"),
                "identifier": match.get("identifier"),
                "round": match.get("round"),
                "round_label": self._round_label(match.get("round")),
                "state": match.get("state"),
                "started_at": match.get("started_at"),
                "completed_at": match.get("completed_at"),
                "underway_at": match.get("underway_at"),
                "scheduled_time": match.get("scheduled_time") or match.get("scheduled_at"),
                "updated_at": match.get("updated_at"),
                "scores_csv": match.get("scores_csv"),
                "score_text": self._score_text(match.get("scores_csv")),
                "player1_id": player1_id,
                "player2_id": player2_id,
                "player1_name": participants.get(player1_id, {}).get("name", "TBD"),
                "player2_name": participants.get(player2_id, {}).get("name", "TBD"),
                "winner_id": winner_id,
                "winner_slot": None,
                "status_text": "",
            }
            if winner_id and winner_id == player1_id:
                entry["winner_slot"] = "player1"
            elif winner_id and winner_id == player2_id:
                entry["winner_slot"] = "player2"

            state = (match.get("state") or "").lower()
            if state == "complete":
                entry["status_text"] = f"{entry['round_label']} · Final"
            elif state == "underway":
                entry["status_text"] = f"{entry['round_label']} · In Progress"
            elif state in {"pending", "open"}:
                entry["status_text"] = f"{entry['round_label']} · Upcoming"
            else:
                entry["status_text"] = entry["round_label"]

            normalized_matches.append(entry)

        def sort_upcoming(item: Dict[str, Any]):
            state = (item.get("state") or "").lower()
            state_rank = {"underway": 0, "pending": 1, "open": 1}.get(state, 2)
            return (
                state_rank,
                item.get("round") if item.get("round") is not None else 0,
                item.get("identifier") or "",
                item.get("id") or 0,
            )

        def sort_completed(item: Dict[str, Any]):
            completed_at = item.get("completed_at") or ""
            return (
                completed_at,
                item.get("id") or 0,
            )

        upcoming_matches = [
            m
            for m in normalized_matches
            if (m.get("state") or "").lower() in {"pending", "open", "underway"}
        ]
        upcoming_matches.sort(key=sort_upcoming)

        completed_matches = [
            m for m in normalized_matches if (m.get("state") or "").lower() == "complete"
        ]
        completed_matches.sort(key=sort_completed, reverse=True)

        underway_matches = [
            m for m in normalized_matches if (m.get("state") or "").lower() == "underway"
        ]

        rounds: Dict[int, list] = {}
        for match in normalized_matches:
            round_number = match.get("round")
            if round_number is None:
                continue
            rounds.setdefault(round_number, []).append(dict(match))

        normalized_rounds = []
        for round_number in sorted(rounds.keys()):
            round_matches = rounds[round_number]
            round_matches.sort(key=lambda m: (m.get("identifier") or "", m.get("id") or 0))
            normalized_rounds.append(
                {
                    "round": round_number,
                    "round_label": self._round_label(round_number),
                    "matches": round_matches,
                }
            )

        current_match: Optional[Dict[str, Any]] = None
        if underway_matches:
            current_match = underway_matches[0]
        elif upcoming_matches:
            current_match = upcoming_matches[0]

        tournament_payload = {
            "id": tournament.get("id"),
            "name": tournament.get("name"),
            "state": tournament.get("state"),
            "game_name": tournament.get("game_name"),
            "url": tournament.get("full_challonge_url")
            or tournament.get("live_image_url")
            or tournament.get("url"),
            "started_at": tournament.get("started_at"),
            "completed_at": tournament.get("completed_at"),
            "updated_at": tournament.get("updated_at"),
            "participants": normalized_participants,
            "matches": normalized_matches,
            "upcoming_matches": upcoming_matches[:8],
            "recent_matches": completed_matches[:8],
            "current_match": current_match,
            "rounds": normalized_rounds,
            "total_participants": len(normalized_participants),
            "total_matches": len(normalized_matches),
        }
        return tournament_payload

    def _fetch(self) -> Dict[str, Any]:
        api_key = self.api_key
        tournament = self.tournament
        if not api_key or not tournament:
            raise RuntimeError("Challonge API key or tournament not configured")

        url = self.API_URL_TEMPLATE.format(tournament=tournament)
        params = {
            "api_key": api_key,
            "include_matches": 1,
            "include_participants": 1,
        }
        if self._session is not None and hasattr(self._session, "get"):
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()
        else:
            query = urllib_parse.urlencode(params)
            full_url = f"{url}?{query}"
            with urllib_request.urlopen(full_url, timeout=10) as resp:
                data = resp.read()
                charset = None
                headers = getattr(resp, "headers", None)
                if headers is not None and hasattr(headers, "get_content_charset"):
                    charset = headers.get_content_charset()
            payload = json.loads(data.decode(charset or "utf-8"))
        return self._normalize_payload(payload)

    def get_tournament(self, force_refresh: bool = False) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            cache_fresh = (
                self._cached_payload is not None
                and not force_refresh
                and (now - self._cached_at) < self._cache_ttl
            )
            if cache_fresh:
                return {
                    "configured": self.is_configured(),
                    "error": self._cached_error,
                    "tournament": self._cached_payload,
                    "fetched_at": self._cached_payload.get("_fetched_at") if self._cached_payload else None,
                    "cached": True,
                }

        if not self.is_configured():
            message = "Challonge integration is not configured."
            with self._lock:
                self._cached_error = message
                self._cached_payload = None
                self._cached_at = now
            return {
                "configured": False,
                "error": message,
                "tournament": None,
                "fetched_at": None,
                "cached": False,
            }

        try:
            tournament_payload = self._fetch()
            fetched_at = datetime.now(timezone.utc).isoformat()
            tournament_payload["_fetched_at"] = fetched_at
            with self._lock:
                self._cached_payload = tournament_payload
                self._cached_error = None
                self._cached_at = now
            return {
                "configured": True,
                "error": None,
                "tournament": tournament_payload,
                "fetched_at": fetched_at,
                "cached": False,
            }
        except Exception as exc:  # noqa: BLE001
            message = f"Failed to fetch Challonge data: {exc}".strip()
            with self._lock:
                self._cached_error = message
                self._cached_at = now
            return {
                "configured": True,
                "error": message,
                "tournament": self._cached_payload,
                "fetched_at": self._cached_payload.get("_fetched_at") if self._cached_payload else None,
                "cached": self._cached_payload is not None,
            }


def get_service() -> ChallongeService:
    return ChallongeService()
