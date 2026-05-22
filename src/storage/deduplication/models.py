from dataclasses import dataclass

MIN_OCR_DUPLICATE_TEXT_LENGTH = 12


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
