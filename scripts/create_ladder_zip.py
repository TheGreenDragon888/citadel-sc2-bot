"""
Zips the relevant files and directories so that Bot can be updated
to ladder or tournaments.
TODO: check all files and folders are present before zipping
"""
import hashlib
import importlib.util
import os
import platform
import shutil
import site
import zipfile
from os import path, remove, walk
from subprocess import Popen, run
from typing import Dict, List, Tuple

import yaml

MY_BOT_NAME: str = "MyBotName"
ZIPFILE_NAME: str = "bot.zip"
# the zip is written here, named after `MyBotName` in config.yml
PUBLISH_DIR: str = "publish"

CONFIG_FILE: str = "config.yml"
ZIP_FILES: List[str] = [
    "config.yml",
    "config.yaml",
    "ladder.py",
    "run.py",
    "terran_builds.yml",
    "terran_builds.yaml",
    "protoss_builds.yml",
    "protoss_builds.yaml",
    "zerg_builds.yml",
    "zerg_builds.yaml",
]
if platform.system() == "Windows":
    EXCLUDE: list[str] = [
        "ares-sc2\\build",
        "ares-sc2\\dist",
        "ares-sc2\\tests",
        "ares-src\\docs",
        "map_analyzer\\pickle_gameinfo",
    ]
    FILETYPES_TO_IGNORE: Tuple = (".c", ".so", "pyx", "pyi")
    ROOT_DIRECTORY = "./"
else:
    EXCLUDE: list[str] = [
        "ares-sc2/build",
        "ares-sc2/dist",
        "ares-sc2/tests",
        "ares-sc2/docs",
        "map_analyzer/pickle_gameinfo",
        "__pycache__",
    ]
    FILETYPES_TO_IGNORE: Tuple = (".c", ".pyd", ".pyx", ".pyi")
    ROOT_DIRECTORY = "./"

ZIP_DIRECTORIES: Dict[str, Dict] = {
    "bot": {"zip_all": True, "folder_to_zip": "bot"},
    "ares-sc2": {"zip_all": True, "folder_to_zip": ""},
    # "sc2_helper": {"zip_all": True, "folder_to_zip": "sc2_helper"},
}
# Libraries copied from the Poetry environment the bot is tested in (versions pinned by
# poetry.lock). The template cloned each library's default branch instead, which put other
# versions in the zip than the tested ones (docs/VERIFY_NOTES.md, "M6 findings").
SITE_PACKAGES_LIBRARIES: List[str] = ["sc2", "map_analyzer", "cython_extensions"]


def zip_dir(dir_path, zip_file):
    """
    Will walk through a directory recursively and add all folders and files to zipfile
    @param dir_path:
    @param zip_file:
    @return:
    """
    for root, _, files in walk(dir_path):
        if any(exclude in root for exclude in EXCLUDE):
            continue
        for file in files:
            if file.lower().endswith(FILETYPES_TO_IGNORE):
                continue
            zip_file.write(
                path.join(root, file),
                path.relpath(path.join(root, file), path.join(dir_path, "..")),
            )


def zip_files_and_directories(zipfile_name: str) -> None:
    """
    @return:
    """

    path_to_zipfile = path.join(ROOT_DIRECTORY, zipfile_name)
    # if the zip file already exists remove it
    if path.isfile(path_to_zipfile):
        remove(path_to_zipfile)
    # create a new zip file
    zip_file = zipfile.ZipFile(path_to_zipfile, "w", zipfile.ZIP_DEFLATED)

    # write directories to the zipfile
    for directory, values in ZIP_DIRECTORIES.items():
        if values["zip_all"]:
            zip_dir(path.join(ROOT_DIRECTORY, directory), zip_file)
        else:
            path_to_dir = path.join(ROOT_DIRECTORY, directory, values["folder_to_zip"])
            zip_dir(path_to_dir, zip_file)

    # write the libraries from the Poetry environment (zip root: `sc2/`, `map_analyzer/`, ...)
    for library in SITE_PACKAGES_LIBRARIES:
        zip_dir(installed_package_dir(library), zip_file)

    # write individual files
    for single_file in ZIP_FILES:
        _path: str = path.join(ROOT_DIRECTORY, single_file)
        if path.isfile(_path):
            zip_file.write(_path, single_file)

    # close the zip file
    zip_file.close()


def get_library_from_site_packages(library_name, project_directory):
    # Find the site packages directory

    site_packages_dir = site.getsitepackages()[0]

    # Construct the library path
    library_path = os.path.join(site_packages_dir, "Lib", "site-packages", library_name)

    # Check if the library path exists
    if not os.path.exists(library_path):
        raise ValueError(f"Library '{library_name}' not found in site packages.")

    # Determine the destination directory in the zip file
    destination_directory = os.path.join(project_directory, library_name)

    # Remove the destination directory if it already exists
    if os.path.exists(destination_directory):
        shutil.rmtree(destination_directory)

    # Copy the library directory into the project directory
    shutil.copytree(library_path, destination_directory)


def zip_content_hash(zip_path: str) -> str:
    """sha256 over every file's name and contents (not timestamps): two builds of the same commit
    and poetry.lock give the same hash, so a rebuilt zip can be matched to a tested one."""
    digest = hashlib.sha256()
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            digest.update(name.encode() + b"\0" + hashlib.sha256(archive.read(name)).digest())
    return digest.hexdigest()


def installed_package_dir(package: str) -> str:
    """The folder of `package` as installed in this Python environment (run the script with
    `poetry run python`, so it is the Poetry environment)."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ValueError(f"Package '{package}' is not installed; run `poetry install` first.")
    package_dir = path.realpath(list(spec.submodule_search_locations)[0])
    if "site-packages" not in package_dir.split(os.sep):
        raise ValueError(f"Package '{package}' found at {package_dir}, not in site-packages.")
    return package_dir


def check_git_status():
    """
    Make sure the branch is master and has no uncommitted changes.
    Not currently used
    @return:
    """
    difference = run("git diff", capture_output=True, text=True)
    branch_name = run("git rev-parse --abbrev-ref HEAD", capture_output=True, text=True)
    assert not difference.stdout, "Uncommitted changes are present"
    assert branch_name.stdout.strip() == "master", "This is not the master branch"


def check_config_values():
    """
    Make sure debug is False.
    """
    config_path: str = path.join(ROOT_DIRECTORY, CONFIG_FILE)
    if path.isfile(config_path):
        with open(path.join(ROOT_DIRECTORY, CONFIG_FILE), "r") as f:
            config = yaml.safe_load(f)
        assert not config["Debug"], "Debug is not False"


def get_zipfile_name() -> str:
    """Attempt to get bot name from config."""
    __user_config_location__: str = path.abspath(".")
    user_config_path: str = path.join(__user_config_location__, CONFIG_FILE)
    zipfile_name = ZIPFILE_NAME
    # attempt to get race and bot name from config file if they exist
    if path.isfile(user_config_path):
        with open(user_config_path) as config_file:
            config: dict = yaml.safe_load(config_file)
            if MY_BOT_NAME in config:
                zipfile_name = f"{config[MY_BOT_NAME]}.zip"
    return zipfile_name


if __name__ == "__main__":
    # get name of bot from config if possible (otherwise use default name)
    os.makedirs(path.join(ROOT_DIRECTORY, PUBLISH_DIR), exist_ok=True)
    zipfile_name = path.join(PUBLISH_DIR, get_zipfile_name())
    print("Setting up poetry environment...")
    # ensure env is setup and dependencies are installed
    p = Popen(["poetry", "install"], cwd=f"{ROOT_DIRECTORY}")
    # makes the process wait, otherwise files get zipped before compile is complete
    p.communicate()
    p_status = p.wait()
    assert p_status == 0, "poetry install failed"

    # at the moment -> ensure debug=False
    print("Checking config values...")
    check_config_values()

    for library in SITE_PACKAGES_LIBRARIES:
        print(f"Zipping {library} from {installed_package_dir(library)}")

    print(f"Zipping files and directories to {zipfile_name}...")
    # copy everything we need into a zip file
    zip_files_and_directories(zipfile_name)

    print(f"Content hash: {zip_content_hash(zipfile_name)}")
    print(f"Ladder zip complete.")
