from dataclasses import dataclass

MIN_OCR_DUPLICATE_TEXT_LENGTH = 12
# 2026-10-31 audit (152 labelled merges): stripped similarity >= 0.6 gave
# 2.5% false merges at 93.5% recall; the old default 0.3 gave 43% false.
MIN_OCR_DUPLICATE_SIMILARITY = 0.6
# @ffmemesbot watermark incl. OCR misreads (@ffemesbot, @tfmemesbot), plus imgflip.com.
OCR_WATERMARK_PATTERN = r"@?[a-z]*mes[a-z]*bot|imgflip\.com"


@dataclass(frozen=True)
class DuplicateResolution:
    dupe_id: int
    original_id: int
    reason: str
    reactions_moved: int
    reactions_dropped: int
    chat_reactions_moved: int
    chat_reactions_dropped: int


@dataclass(frozen=True)
class DeduplicationResult:
    meme_id: int
    duplicate_of: int | None = None
    reason: str | None = None
    resolution: DuplicateResolution | None = None

    @property
    def duplicate_found(self) -> bool:
        return self.duplicate_of is not None
