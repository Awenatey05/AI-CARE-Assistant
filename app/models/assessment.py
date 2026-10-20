"""Structured output: what the model must return for one case.

The model returns a JSON label for each indicator, validated with Pydantic.
Score, band and urgent flags are never taken from the model; they are
computed in Python (app/services/scoring.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Indicators 6 and 10 each cover two situations, recorded as subtype a or b.
SUBTYPE_INDICATORS = {6, 10}


class IndicatorLabel(BaseModel):
    """The model's label for one of the 10 indicators."""

    id: int = Field(ge=1, le=10)                 # indicator number, 1 to 10 only
    present: bool                                # is the indicator in the report?
    subtype: Literal["a", "b"] | None = None     # only for indicators 6 and 10
    quote: str | None = None                     # supporting quote from the report

    @model_validator(mode="after")
    def check_quote_and_subtype(self) -> IndicatorLabel:
        """Rules between fields: no indicator without evidence, subtype only for 6 and 10."""
        # An empty quote ("" or spaces) counts as no quote.
        if self.quote is not None and not self.quote.strip():
            self.quote = None

        # Present needs a supporting quote; not present has none.
        if self.present and self.quote is None:
            raise ValueError(f"indicator {self.id} is present but has no quote")
        if not self.present and self.quote is not None:
            raise ValueError(f"indicator {self.id} is not present but has a quote")

        # Subtype a or b is required for 6 and 10 when present, and not allowed otherwise.
        if self.present and self.id in SUBTYPE_INDICATORS:
            if self.subtype is None:
                raise ValueError(f"indicator {self.id} is present but has no subtype (a or b)")
        elif self.subtype is not None:
            raise ValueError(f"indicator {self.id} should not have a subtype")

        return self


class Assessment(BaseModel):
    """The model's full answer for one case: a label for each of the 10 indicators."""

    case_id: str                       # returned by the model, but never trusted
    indicators: list[IndicatorLabel]   # exactly one label per indicator
    summary: str = ""                  # short summary for officers; never used for scoring

    @field_validator("indicators")
    @classmethod
    def all_ten_indicators(cls, indicators: list[IndicatorLabel]) -> list[IndicatorLabel]:
        """All ten indicators present, each exactly once."""
        ids = [label.id for label in indicators]
        missing = sorted(set(range(1, 11)) - set(ids))
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if missing:
            raise ValueError(f"missing indicators: {missing}")
        if duplicates:
            raise ValueError(f"duplicate indicators: {duplicates}")
        # Keep them in order 1 to 10.
        return sorted(indicators, key=lambda label: label.id)
