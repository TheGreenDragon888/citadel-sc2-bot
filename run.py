import os
import random
import sys
from os import path
from pathlib import Path
import platform
from typing import List, Tuple
from loguru import logger

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

import yaml

from bot.main import CitadelBot
from ladder import run_ladder_game

plt = platform.system()
# change if non default setup / linux
# if having issues with this, modify `map_list` below manually
if plt == "Windows":
    MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
elif plt == "Darwin":
    MAPS_PATH: str = "/Applications/StarCraft II/Maps"
elif plt == "Linux":
    # SC2 Linux package: python-sc2 finds the game through SC2PATH,
    # and the maps live directly inside its `Maps` folder (case-sensitive)
    MAPS_PATH: str = path.join(
        os.environ.get("SC2PATH", path.expanduser("~/StarCraftII")), "Maps"
    )
else:
    logger.error(f"{plt} not supported")
    sys.exit()

CONFIG_FILE: str = "config.yml"
MAP_FILE_EXT: str = "SC2Map"
MY_BOT_NAME: str = "MyBotName"
MY_BOT_RACE: str = "MyBotRace"

# AI Arena map pool (docs/DESIGN.md §2)
POOL_MAPS: List[str] = [
    "MagannathaAIE_v2",
    "UltraloveAIE_v2",
    "LeyLinesAIE_v3",
    "TorchesAIE_v4",
    "PylonAIE_v4",
    "PersephoneAIE_v4",
    "IncorporealAIE_v4",
]


def load_bot_config() -> Tuple[str, Race]:
    """Read the bot name and race from `config.yml` if they exist."""
    bot_name: str = "MyBot"
    race: Race = Race.Random

    __user_config_location__: str = path.abspath(".")
    user_config_path: str = path.join(__user_config_location__, CONFIG_FILE)
    # attempt to get race and bot name from config file if they exist
    if path.isfile(user_config_path):
        with open(user_config_path) as config_file:
            config: dict = yaml.safe_load(config_file)
            if MY_BOT_NAME in config:
                bot_name = config[MY_BOT_NAME]
            if MY_BOT_RACE in config:
                race = Race[config[MY_BOT_RACE].title()]
    return bot_name, race


def get_map_list() -> List[str]:
    """Pool maps found in `MAPS_PATH`, or the whole pool list if none are found.

    Other maps in the folder are ignored: a non-pool map can hold unit types python-sc2
    can't parse (e.g. AcropolisAIE crashed with `2046 is not a valid UnitTypeId`).
    """
    found: set = {
        p.name.replace(f".{MAP_FILE_EXT}", "")
        for p in Path(MAPS_PATH).glob(f"*.{MAP_FILE_EXT}")
        if p.is_file()
    }
    map_list: List[str] = [m for m in POOL_MAPS if m in found]
    missing: List[str] = [m for m in POOL_MAPS if m not in found]
    if map_list and missing:
        logger.warning(f"Pool maps missing from {MAPS_PATH}: {', '.join(missing)}")
    if len(map_list) == 0:
        logger.error(f"Can't find maps, please check `MAPS_PATH` in `run.py'")
        logger.info("Trying back up option")
        logger.info(
            f"\nLooking for maps in {MAPS_PATH} but didn't find anything. \n"
            f"If this path is correct please ensure maps are present. \n"
            f"If this path is incorrect please edit the `MAPS_PATH` in `run.py` \n"
        )
        map_list = list(POOL_MAPS)
    return map_list


def main():
    bot_name, race = load_bot_config()
    bot1 = Bot(race, CitadelBot(), bot_name)

    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot1)
        print(result, " against opponent ", opponentid)
    else:
        # Local game
        map_list: List[str] = get_map_list()
        random_race = random.choice([Race.Zerg, Race.Terran, Race.Protoss])
        print("Starting local game...")
        run_game(
            maps.get(random.choice(map_list)),
            [
                bot1,
                Computer(random_race, Difficulty.CheatVision, ai_build=AIBuild.Macro),
            ],
            realtime=False,
        )


# Start game
if __name__ == "__main__":
    main()
