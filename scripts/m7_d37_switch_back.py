"""m7_d37_switch_back.py ROOT GROUP...: M7 D37 experiments (dev only; scripts/ is not in the ladder zip).
Switches Phase 2 fight-rule groups back to their pre-Phase-2 behaviour in the checkout at ROOT.
Groups: C1s (step-out), HOLD (C1 fallback anchor + C9 hysteresis/disengage), C2 (eligibility),
C3 (retreat fire), C4 (launch gate; or one part: C4h home-fight wait, C4r remembered-army
gate, C4i intel wait), C5 (out-range penalty), ALL."""
import sys
from pathlib import Path

EDITS = {
    "C1s": [("bot/army/army.py",
             "            if mode in (HOLD, MOVE, RETREAT) and micro.out_rangers(unit, visible):",
             "            if False and mode in (HOLD, MOVE, RETREAT) and micro.out_rangers(unit, visible):  # D37: C1 step-out off")],
    "HOLD": [("bot/army/army.py",
              '''        base = anchor
        steps = 0''',
              '''        return anchor  # D37: C1 fallback anchor and C9's fallback off
        base = anchor
        steps = 0'''),
             ("bot/army/army.py",
              "                engages = home_engages(level, needed, self._home_engaged, DEFEND_DISENGAGE_AT)",
              "                engages = level >= needed  # D37: C9 hysteresis off\n                self._home_engaged = False"),
             ("bot/army/army.py",
              "                elif self._home_engaged:\n                    self._home_engaged = False\n                    self._disengage(now, level)",
              "                elif False:  # D37: C9 disengage off\n                    self._home_engaged = False\n                    self._disengage(now, level)")],
    "C2": [("bot/army/army.py",
            "        return [u for u in defenders if not micro.has_weapon(u) or any(micro.can_hit(u, e) for e in enemies)]",
            "        return list(defenders)  # D37: C2 eligibility off")],
    "C3": [("bot/army/micro.py",
            "        targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory and _fights_back(e)]",
            "        targets = [e for e in enemies if _can_hit(unit, e) and not e.is_memory]  # D37: C3 off"),
           ("bot/army/micro.py",
            "            and retreat_may_shoot(unit.movement_speed, speeds, bool(targets))\n",
            "")],
    "C4": [("bot/army/army.py",
            "            since_home_fight_s=since_fight, army_level=army_level,\n            intel_fresh=total > 0 and fresh >= LAUNCH_INTEL_FRESH_FRACTION * total,",
            "            # D37: C4 launch gate off\n            since_home_fight_s=math.inf, army_level=None, intel_fresh=True,")],
    "C4h": [("bot/army/army.py",
             "            since_home_fight_s=since_fight, army_level=army_level,",
             "            since_home_fight_s=math.inf, army_level=army_level,  # D37: C4 home-fight wait off")],
    "C4r": [("bot/army/army.py",
             "            since_home_fight_s=since_fight, army_level=army_level,",
             "            since_home_fight_s=since_fight, army_level=None,  # D37: C4 remembered-army gate off")],
    "C4i": [("bot/army/army.py",
             "            intel_fresh=total > 0 and fresh >= LAUNCH_INTEL_FRESH_FRACTION * total,",
             "            intel_fresh=True,  # D37: C4 intel wait off")],
    "C5": [("bot/army/engagement.py",
            "        penalty = outrange_penalty(self.outranged_share(own, enemy), OUTRANGE_PENALTY_PER_SHARE)",
            "        penalty = 0  # D37: C5 out-range penalty off")],
}


def main() -> None:
    root = Path(sys.argv[1])
    groups = sys.argv[2:]
    if groups == ["ALL"]:
        groups = ["C1s", "HOLD", "C2", "C3", "C4", "C5"]
    for g in groups:
        for rel, old, new in EDITS[g]:
            p = root / rel
            s = p.read_text()
            assert s.count(old) == 1, (g, rel, old[:60], s.count(old))
            p.write_text(s.replace(old, new))
        print(f"switched back: {g}")


main()
