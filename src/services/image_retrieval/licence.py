"""S62 — licence category enforcement (only openly-licensed sources)."""

from __future__ import annotations

from enum import StrEnum


class LicenceCategory(StrEnum):
    CC0 = "cc0"
    CC_BY = "cc-by"
    CC_BY_SA = "cc-by-sa"
    CC_BY_ND = "cc-by-nd"
    CC_BY_NC = "cc-by-nc"
    CC_BY_NC_SA = "cc-by-nc-sa"
    CC_BY_NC_ND = "cc-by-nc-nd"
    PDM = "pdm"
    ODC_ODBL = "odc-odbl"
    USGOV = "usgov"
    UNKNOWN = "unknown"


class LicenceAcceptance(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNVERIFIABLE = "unverifiable"


# Only these categories are acceptable for use — per ADR-008/FR-4.1-4.7,
# any restrictive or unverifiable licence is rejected before scoring
# (T63.4 depends on this ordering: licence check precedes any similarity
# score computation).
_ACCEPTABLE = {
    LicenceCategory.CC0,
    LicenceCategory.CC_BY,
    LicenceCategory.CC_BY_SA,
    LicenceCategory.PDM,
    LicenceCategory.ODC_ODBL,
    LicenceCategory.USGOV,
}


def check_licence(licence: LicenceCategory) -> LicenceAcceptance:
    if licence == LicenceCategory.UNKNOWN:
        return LicenceAcceptance.UNVERIFIABLE
    if licence in _ACCEPTABLE:
        return LicenceAcceptance.ACCEPTED
    return LicenceAcceptance.REJECTED
