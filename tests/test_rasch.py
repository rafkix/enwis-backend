"""Rasch (1PL IRT) kalibratsiya va test yig'ish mantig'i uchun testlar.

Bu modul tashqi bog'liqliksiz (faqat `math`) ishlagani uchun DB
fixture'lari kerak emas — sof matematik testlar.
"""

import math
import random

from app.modules.questions.rasch import (
    calibrate,
    item_information,
    select_items_for_ability,
)


def _simulate_responses(true_b: dict[str, float], true_theta: dict[str, float], seed: int = 1):
    rng = random.Random(seed)

    def p(theta, b):
        return 1 / (1 + math.exp(-(theta - b)))

    responses = []
    for user, theta in true_theta.items():
        for item, b in true_b.items():
            correct = rng.random() < p(theta, b)
            responses.append((user, item, correct))
    return responses


def test_calibrate_recovers_relative_item_ordering():
    true_b = {f"item{i}": (i - 4) * 0.8 for i in range(8)}
    true_theta = {f"user{u}": random.Random(u).gauss(0, 1) for u in range(50)}
    responses = _simulate_responses(true_b, true_theta)

    result = calibrate(responses)

    assert result.converged
    assert result.n_items == 8
    # Estimated difficulties should preserve the true relative ordering.
    ordered_true = sorted(true_b, key=lambda k: true_b[k])
    ordered_est = sorted(result.item_difficulty, key=lambda k: result.item_difficulty[k])
    assert ordered_true == ordered_est


def test_calibrate_skips_items_with_no_variance():
    # item_always_right has no incorrect answers -> can't be calibrated.
    responses = [
        ("u1", "item_always_right", True),
        ("u2", "item_always_right", True),
        ("u1", "item_mixed", True),
        ("u2", "item_mixed", False),
        ("u3", "item_mixed", True),
    ]
    result = calibrate(responses)
    assert "item_always_right" in result.skipped_items


def test_calibrate_empty_input():
    result = calibrate([])
    assert result.item_difficulty == {}
    assert result.n_items == 0


def test_select_items_for_ability_picks_closest_b():
    candidates = [("easy", -2.0), ("mid", 0.0), ("hard", 2.0), ("very_hard", 3.5)]
    selected = select_items_for_ability(candidates, target_theta=1.8, n_items=2)
    assert selected[0] == "hard"


def test_select_items_respects_min_gap():
    candidates = [("a", 0.0), ("b", 0.05), ("c", 0.1), ("d", 2.0)]
    selected = select_items_for_ability(candidates, target_theta=0.0, n_items=2, min_gap=1.0)
    assert set(selected) == {"a", "d"}


def test_item_information_peaks_at_theta_equals_b():
    info_at_match = item_information(theta=1.0, b=1.0)
    info_off = item_information(theta=1.0, b=3.0)
    assert info_at_match > info_off
    assert info_at_match == 0.25  # P(1-P) is maximal (0.25) when theta == b
