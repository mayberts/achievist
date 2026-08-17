"""
Milestone definitions: thresholds, badge tiers, and what each one is worth.

Lives in its own module because two callers need it and must never disagree —
/api/milestones (which draws the badges) and the leaderboard's
milestone_points column (which ranks people by them). Putting the table in
either caller would make the other import it sideways.
"""

BRONZE, SILVER, GOLD, PLATINUM, DIAMOND = "bronze", "silver", "gold", "platinum", "diamond"

# (threshold, badge tier) for total achievements unlocked.
ACHIEVEMENT_MILESTONES: list[tuple[int, str]] = [
    (100, BRONZE),
    (250, BRONZE),
    (500, SILVER),
    (1_000, SILVER),
    (2_500, GOLD),
    (5_000, GOLD),
    (7_500, PLATINUM),
    (10_000, PLATINUM),
    (15_000, DIAMOND),
    (20_000, DIAMOND),
    (25_000, DIAMOND),
    (50_000, DIAMOND),
]

# (threshold, badge tier) for games taken all the way to 100%.
MASTERED_MILESTONES: list[tuple[int, str]] = [
    (1, BRONZE),
    (5, BRONZE),
    (10, SILVER),
    (25, SILVER),
    (50, GOLD),
    (100, PLATINUM),
    (150, DIAMOND),
    (200, DIAMOND),
]

# Taking a whole game to 100% is worth far more than any single unlock, so the
# mastered thresholds — which are small numbers — are scaled up before being
# compared against achievement milestones on the same leaderboard.
MASTERED_POINTS_PER_GAME = 100


def achievement_milestone_points(threshold: int) -> int:
    """A milestone is worth its own threshold, which keeps the whole scheme
    explicable in one sentence and needs no lookup table to justify."""
    return threshold


def mastered_milestone_points(threshold: int) -> int:
    return threshold * MASTERED_POINTS_PER_GAME


def achievement_point_pairs() -> list[tuple[int, int]]:
    return [(t, achievement_milestone_points(t)) for t, _ in ACHIEVEMENT_MILESTONES]


def mastered_point_pairs() -> list[tuple[int, int]]:
    return [(t, mastered_milestone_points(t)) for t, _ in MASTERED_MILESTONES]


def sql_points_values(pairs: list[tuple[int, int]]) -> str:
    """
    Render (threshold, points) pairs as the body of a SQL VALUES list.

    Interpolated into the leaderboard query rather than bound as parameters:
    a VALUES list can't be passed as one placeholder, and these are
    module-level integer constants that never touch user input. int() is
    applied anyway so a bad edit to the tables above fails loudly here
    instead of reaching the database.
    """
    return ", ".join(f"({int(threshold)}, {int(points)})" for threshold, points in pairs)


def total_points_for(achievements_unlocked: int, games_mastered: int) -> int:
    """Points from every milestone the given totals have passed.

    Mirrors the leaderboard's SQL; kept here so tests can assert the two
    agree without reimplementing the sum.
    """
    return sum(
        points for threshold, points in achievement_point_pairs() if threshold <= achievements_unlocked
    ) + sum(
        points for threshold, points in mastered_point_pairs() if threshold <= games_mastered
    )
