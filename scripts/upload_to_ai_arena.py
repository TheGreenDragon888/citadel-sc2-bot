import hashlib
import sys
from os import path, environ
from typing import Union

import requests
import yaml
from loguru import logger

API_TOKEN_ENV: str = "UPLOAD_API_TOKEN"
BOT_ID_ENV: str = "UPLOAD_BOT_ID"
CONFIG_FILE: str = "config.yml"
AUTO_UPLOAD_TO_AIARENA: str = "AutoUploadToAiarena"
BOT_ZIP_PUBLICLY_DOWNLOADABLE: str = "BotZipPubliclyDownloadable"
BOT_DATA_PUBLICLY_DOWNLOADABLE: str = "BotDataPubliclyDownloadable"
BOT_DATA_ENABLED: str = "BotDataEnabled"
MY_BOT_NAME: str = "MyBotName"
# the zip scripts/create_ladder_zip.py writes: publish/<MyBotName>.zip (the template read "bot.zip",
# which no step writes)
PUBLISH_DIR: str = "publish"

TOKEN: str = environ.get(API_TOKEN_ENV)
BOT_ID: str = environ.get(BOT_ID_ENV)
URL: str = f"https://aiarena.net/api/bots/{BOT_ID}/"


def get_bot_description() -> str:
    """
    Generate bot description
    REPLACE WITH OWN LOGIC HERE
    By default, attempts to get bot name from config
    and generate a basic description.
    """
    bot_name: str = "MyBot"
    if name := retrieve_value_from_config(MY_BOT_NAME):
        bot_name = name

    return (
        f"# {bot_name}\n\n" "Made with [ares-sc2](https://github.com/AresSC2/ares-sc2)"
    )


def retrieve_value_from_config(string: str) -> Union[str, bool, None]:
    __user_config_location__: str = path.abspath(".")
    user_config_path: str = path.join(__user_config_location__, CONFIG_FILE)
    # attempt to get race and bot name from config file if they exist
    if path.isfile(user_config_path):
        with open(user_config_path) as config_file:
            config: dict = yaml.safe_load(config_file)
            if string in config:
                return config[string]


if __name__ == "__main__":
    can_upload: bool = False
    if upload := retrieve_value_from_config(AUTO_UPLOAD_TO_AIARENA):
        can_upload = upload
    # `--upload`: upload now even with AutoUploadToAiarena off (M6: one upload from a dev
    # machine, without making every push to main upload)
    if "--upload" in sys.argv[1:]:
        can_upload = True

    if not can_upload:
        logger.info(
            "Auto update to aiarena not enabled, please set "
            "AutoUploadToAiarena option in config to `True`"
        )

    elif not TOKEN or not BOT_ID:
        logger.error(f"Set {API_TOKEN_ENV} and {BOT_ID_ENV} (environment variables) to upload")
        sys.exit(1)

    else:
        logger.info("Uploading bot")
        bot_zip_public = retrieve_value_from_config(BOT_ZIP_PUBLICLY_DOWNLOADABLE)
        if bot_zip_public is None:
            bot_zip_public = False

        bot_data_public = retrieve_value_from_config(BOT_DATA_PUBLICLY_DOWNLOADABLE)
        if bot_data_public is None:
            bot_data_public = False

        bot_data_enabled = retrieve_value_from_config(BOT_DATA_ENABLED)
        if bot_data_enabled is None:
            bot_data_enabled = True

        zip_path = path.join(PUBLISH_DIR, f"{retrieve_value_from_config(MY_BOT_NAME) or 'MyBot'}.zip")
        with open(zip_path, "rb") as f:
            logger.info(f"{zip_path}: md5 {hashlib.md5(f.read()).hexdigest()} (AI Arena reports bot_zip_md5hash)")
        with open(zip_path, "rb") as bot_zip:
            request_headers = {
                "Authorization": f"Token {TOKEN}",
            }
            request_data = {
                "bot_zip_publicly_downloadable": bot_zip_public,
                "bot_data_publicly_downloadable": bot_data_public,
                "bot_data_enabled": bot_data_enabled,
                "wiki_article_content": get_bot_description(),
            }
            request_files = {
                "bot_zip": bot_zip,
            }
            logger.info(URL)
            response = requests.patch(
                URL, headers=request_headers, data=request_data, files=request_files
            )
            logger.info(response)
            logger.info(response.content)
