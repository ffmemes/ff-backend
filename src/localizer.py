import logging
from pathlib import Path

import yaml

# not sure where to put this const
DEFAULT_LANG = "en"


def load():
    """Concatenates all .yml files"""

    localizations = {}
    localization_files_dir = Path(__file__).parent.parent / "static/localization"
    for localization_file in localization_files_dir.iterdir():
        if localization_file.is_dir() or localization_file.suffix != ".yml":
            continue

        with open(localization_file, "r") as f:
            localizations |= yaml.safe_load(f)

    logging.info(f"Loaded {len(localizations)} localization strings.")
    return localizations


def t(key: str, lang: str | None) -> str:
    if lang is None or lang not in localizations[key]:
        lang = DEFAULT_LANG

    return localizations[key][lang]


localizations = load()
