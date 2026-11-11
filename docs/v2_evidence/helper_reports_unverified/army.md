# bot/army audit (IN PROGRESS - partial notes, not yet verified against library source)

Status: read fully so far: army.py, micro.py, engagement.py, squads.py, attack_decision.py, ranges.py, main.py.
Still to read: blink.py, counterattack.py, endgame.py, templar.py, constants.py (army parts), DESIGN.md 4.5-4.7.

## Candidate findings (unverified leads, to be checked)
- micro.out_rangers (micro.py:94): `reach(e, unit) + OUTRANGED_REACH_BUFFER` - reach() can return None? (outranges() true implies enemy weapon_range not None, so probably safe) - check.
- micro.fight KITERS includes SENTRY/VOIDRAY/ORACLE: game-data weapon absent for some -> ShootTargetInRange behaviour? check ares source.
- army._groups: get_squads(role=ATTACKING, squad_radius, unit_type=set) - check signature and whether squad objects have main_squad/squad_units/squad_position.
- army.micro: `self.last_level or -1` - level 0 (LOSS_EMPHATIC) becomes -1 (harmless?) check blink_finish.
- army._decide recall: only when defend_target is None and threat is not None.
- attack_decision: `held` uses state_since=0.0 at game start.
- engagement.level: predict_engage signature / defender_player; u.can_attack for structures.
