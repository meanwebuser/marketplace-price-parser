import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyzer.output import cheapest_per_tier
from families.minimax import CONFIG


def test_unverified_price_cannot_win_cheapest_ranking():
    unchecked = {"tier": "Max", "duration": "1m", "delivery": "new_account", "glitched": False, "price_rub": 1, "price_verified": False}
    verified = {"tier": "Max", "duration": "1m", "delivery": "new_account", "glitched": False, "price_rub": 4275, "price_verified": True}
    result = cheapest_per_tier([unchecked, verified], CONFIG)
    assert result[("Max", "1m", "new_account")]["price_rub"] == 4275
