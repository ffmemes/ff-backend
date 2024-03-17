import logging
from pathlib import Path

import yaml

# not sure where to put this const
DEFAULT_LANG = "en"

ALMOST_CIS_LANGUAGES = [
    "uk",
    "ru",
    "bg",
    "be",
    "sr",
    "hr",
    "bs",
    "mk",
    "sl",
    "kz",
    "ky",
    "tg",
    "tt",
    "uz",
    "mn",
    "az",
]


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
    if lang in localizations[key]:
        return localizations[key][lang]

    if lang in ALMOST_CIS_LANGUAGES and "ru" in localizations[key]:
        return localizations[key]["ru"]

    return localizations[key][DEFAULT_LANG]


localizations = load()
