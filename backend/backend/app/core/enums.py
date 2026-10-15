"""Shared enumerations. Stored as plain strings in the database."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    USER_CONFIRMED = "USER_CONFIRMED"
    VERIFIED = "VERIFIED"
    CONFLICT = "CONFLICT"
    SUPERSEDED = "SUPERSEDED"


class ConfirmationBasis(StrEnum):
    OFFICIAL_SOURCE = "OFFICIAL_SOURCE"
    SECONDARY_SOURCE = "SECONDARY_SOURCE"
    NO_SOURCE = "NO_SOURCE"


class InputMethod(StrEnum):
    AUTOMATED = "automated"
    SCREENSHOT = "screenshot"
    PHOTO = "photo"
    PDF = "pdf"
    TYPED = "typed"
    CSV = "csv"
    URL = "url"


class ContentType(StrEnum):
    ECONOMIC_RELEASE = "economic_release"
    CALENDAR = "calendar"
    CB_STATEMENT = "cb_statement"
    CB_PROJECTIONS = "cb_projections"
    RATE_EXPECTATIONS = "rate_expectations"
    MARKET_PRICES = "market_prices"
    SPEECH = "speech"
    UNKNOWN = "unknown"


class SourceStatus(StrEnum):
    OK = "OK"
    DELAYED = "DELAYED"
    FAILED = "FAILED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class SourceTier(StrEnum):
    TIER_1 = "1"
    TIER_2 = "2"
    TIER_3 = "3"
    TIER_4 = "4"
    TIER_M = "M"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Direction(StrEnum):
    HAWKISH = "Hawkish"
    DOVISH = "Dovish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"


class Bias(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Grade(StrEnum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    NO_TRADE = "NO TRADE"


GRADE_ORDER = [Grade.NO_TRADE, Grade.C, Grade.B, Grade.A, Grade.A_PLUS]
