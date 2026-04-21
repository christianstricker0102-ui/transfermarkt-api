"""
Regression-Tests fuer parse_str_to_int (app/schemas/base.py).

Deutsche TM-Seiten liefern Tausender-Separator als Punkt ("2.970"). Ohne Fix
macht int(float("2.970")) = 2 — minutesPlayed/appearances werden verstuemmelt.
Diese Tests sichern den Fix ab.
"""
import pytest

from app.schemas.players.stats import PlayerStat


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Tausender-Separator (der Bug)
        ("2.970", 2970),
        ("1.530", 1530),
        ("1.170", 1170),
        ("1.234.567", 1234567),
        # Kleine Integer ohne Separator
        ("810", 810),
        ("90", 90),
        ("0", 0),
        # Vierstellig ohne Separator (sollte unveraendert bleiben)
        ("2970", 2970),
    ],
)
def test_minutes_played_thousand_separator(raw, expected):
    """minutesPlayed darf nicht durch den DE-Tausender-Punkt verstuemmelt werden."""
    stat = PlayerStat(
        competitionId="L1",
        competitionName="Bundesliga",
        seasonId="25/26",
        clubId="27",
        minutesPlayed=raw,
    )
    assert stat.minutes_played == expected, (
        f"minutesPlayed '{raw}' → {stat.minutes_played}, erwartet {expected}"
    )


@pytest.mark.parametrize("raw,expected", [("33", 33), ("1.234", 1234), ("0", 0)])
def test_appearances_thousand_separator(raw, expected):
    stat = PlayerStat(
        competitionId="L1",
        competitionName="Bundesliga",
        seasonId="25/26",
        clubId="27",
        appearances=raw,
    )
    assert stat.appearances == expected
