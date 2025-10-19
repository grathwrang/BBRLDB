import os

import pytest

import storage
import tournament_engine


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    original_classes = list(storage.DB_FILES.keys())
    patched_db_files = {
        wc: os.path.join(tmp_path, f"{wc.lower()}_db.json") for wc in original_classes
    }
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "DB_FILES", patched_db_files)
    monkeypatch.setattr(storage, "SCHEDULE_FP", os.path.join(tmp_path, "schedule.json"))
    monkeypatch.setattr(storage, "JUDGING_FP", os.path.join(tmp_path, "judging.json"))
    monkeypatch.setattr(storage, "JUDGING_LOCK_FP", os.path.join(tmp_path, "judging.lock"))
    monkeypatch.setattr(storage, "TOURNAMENTS_FP", os.path.join(tmp_path, "tournaments.json"))
    storage.ensure_dirs()
    for wc in original_classes:
        storage.save_db(
            wc,
            {
                "robots": {},
                "history": [],
                "next_match_id": 1,
                "settings": {"K": storage.DEFAULT_K, "ko_weight": storage.KO_WEIGHT},
            },
        )
    return patched_db_files


@pytest.fixture
def present_robots(isolated_storage):
    weight_class = next(iter(isolated_storage.keys()))
    db = storage.load_db(weight_class)
    db["robots"] = {
        "Atlas": {"present": True},
        "Blazer": {"present": True},
        "Cyclone": {"present": True},
        "Dynamo": {"present": True},
        "Echo": {"present": False},
    }
    storage.save_db(weight_class, db)
    loaded = storage.load_all()
    robots = [name for name, info in loaded[weight_class]["robots"].items() if info.get("present")]
    return {"weight_class": weight_class, "robots": robots}


def test_single_elimination_bracket_advancement(present_robots):
    robots = present_robots["robots"][:4]
    bracket = tournament_engine.seed_bracket(robots, elimination_type="single", max_robots=4)
    winners_rounds = bracket["order"]["winners"]
    assert len(winners_rounds[0]) == 2

    first_match = winners_rounds[0][0]
    participants = tournament_engine.resolve_match_participants(bracket, first_match)
    assert participants["red"] == robots[0]
    assert participants["white"] == robots[1]

    tournament_engine.record_match_result(bracket, first_match, robots[0])
    tournament_engine.record_match_result(bracket, winners_rounds[0][1], robots[2])

    final_match = winners_rounds[1][0]
    final_participants = tournament_engine.resolve_match_participants(bracket, final_match)
    assert {final_participants[slot] for slot in ("red", "white")} == {robots[0], robots[2]}

    tournament_engine.record_match_result(bracket, final_match, robots[0])
    final_state = bracket["matches"][final_match]
    assert final_state["result"]["winner"] == robots[0]


def test_double_elimination_losers_progression(present_robots):
    robots = present_robots["robots"][:4]
    bracket = tournament_engine.seed_bracket(robots, elimination_type="double", max_robots=4)

    winners_rounds = bracket["order"]["winners"]
    assert len(winners_rounds[0]) == 2
    losers_rounds = bracket["order"]["losers"]
    assert losers_rounds, "Losers bracket should be seeded"

    first_match, second_match = winners_rounds[0]
    tournament_engine.record_match_result(bracket, first_match, robots[0])
    tournament_engine.record_match_result(bracket, second_match, robots[2])

    first_loser_match = losers_rounds[0][0]
    first_loser_participants = tournament_engine.resolve_match_participants(bracket, first_loser_match)
    assert {first_loser_participants["red"], first_loser_participants["white"]} == {robots[1], robots[3]}

    tournament_engine.record_match_result(bracket, first_loser_match, robots[1])

    winners_final = winners_rounds[1][0]
    tournament_engine.record_match_result(bracket, winners_final, robots[0])

    second_loser_match = bracket["order"]["losers"][1][0]
    second_loser_participants = tournament_engine.resolve_match_participants(bracket, second_loser_match)
    assert {second_loser_participants["red"], second_loser_participants["white"]} == {robots[1], robots[2]}

    tournament_engine.record_match_result(bracket, second_loser_match, robots[1])

    grand_final = bracket["order"]["finals"][0]
    final_participants = tournament_engine.resolve_match_participants(bracket, grand_final)
    assert {final_participants["red"], final_participants["white"]} == {robots[0], robots[1]}


def test_multiple_tournaments_persist(isolated_storage, present_robots):
    robots = present_robots["robots"][:4]
    weight_class = present_robots["weight_class"]

    bracket_a = tournament_engine.seed_bracket(robots, elimination_type="single", max_robots=4)
    storage.update_tournament(
        "alpha",
        {
            "name": "Event Alpha",
            "weight_class": weight_class,
            "elimination": "single",
            "max_robots": 4,
            "robots": list(bracket_a.get("selected", robots)),
            "bracket": bracket_a,
        },
    )

    bracket_b = tournament_engine.seed_bracket(list(reversed(robots)), elimination_type="double", max_robots=4)
    storage.update_tournament(
        "beta",
        {
            "name": "Event Beta",
            "weight_class": weight_class,
            "elimination": "double",
            "max_robots": 4,
            "robots": list(bracket_b.get("selected", robots)),
            "bracket": bracket_b,
        },
    )

    tournaments = storage.load_tournaments()
    assert set(tournaments.keys()) == {"alpha", "beta"}
    assert tournaments["alpha"]["elimination"] == "single"
    assert tournaments["beta"]["elimination"] == "double"
    assert tournaments["beta"]["bracket"]["format"] == "double"
