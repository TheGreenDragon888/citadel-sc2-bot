"""Every TUNE value and threshold Citadel uses (CLAUDE.md rule).

Section references (§) point at docs/DESIGN.md. Values that come from game data are
read at runtime instead of being listed here.
"""

# §1, §4.7: the ladder ends a game as a tie at 80,640 game loops (60:00 game time)
LADDER_TIE_GAME_SECONDS: int = 3600
