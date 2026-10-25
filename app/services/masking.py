"""Masking names and phone numbers (Presidio) before text is embedded or sent to the LLM.

Presidio's name finder (spaCy) misses many Ghanaian names, especially names
that are also English words (Comfort, Patience, Mercy). So three things are
combined:
  1. spaCy's English model (en_core_web_lg) finds most names,
  2. Ghana phone numbers and names after a title (Mrs, Nurse, ...) are matched by pattern,
  3. names the system already knows for this case (the child's name on the
     form or in the sheet) are always masked.
The original text is never changed; this returns a masked copy.
"""

from __future__ import annotations

import re
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import PhoneRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# 1. CONFIGURATION
SPACY_MODEL = "en_core_web_lg"
ENTITIES = ["PERSON", "PHONE_NUMBER"]
PLACEHOLDERS = {"PERSON": "[NAME]", "PHONE_NUMBER": "[PHONE]"}
TITLES = r"(?:Mr|Mrs|Ms|Miss|Dr|Nurse|Madam)\.?"
MIN_NAME_LENGTH = 3   # parts of a known name shorter than this are not masked on their own
# Presidio matches patterns ignoring case by default; names must match case exactly,
# or "the nurse he had" becomes a name and "comfort" (the word) is masked like "Comfort".
CASE_SENSITIVE = re.DOTALL | re.MULTILINE


# 2. BUILD THE ANALYSER ONCE
@lru_cache(maxsize=1)
def analyzer() -> AnalyzerEngine:
    """spaCy for names, plus Ghana phone numbers and names after a title."""
    nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": SPACY_MODEL}],
    }).create_engine()
    engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    engine.registry.add_recognizer(PhoneRecognizer(supported_regions=["GH"]))
    engine.registry.add_recognizer(PatternRecognizer(
        supported_entity="PERSON",
        name="TitledNameRecognizer",
        patterns=[Pattern("name after a title", rf"(?<={TITLES} )[A-Z][a-z]+(?: [A-Z][a-z]+)?", 0.85)],
        global_regex_flags=CASE_SENSITIVE,
    ))
    return engine


# 3. MASK
def known_name_recognizer(known_names: list[str]) -> PatternRecognizer:
    """Every part of every known name ("Comfort Atinga" -> "Comfort", "Atinga") is always masked."""
    parts = sorted({part for name in known_names for part in name.split() if len(part) >= MIN_NAME_LENGTH})
    return PatternRecognizer(supported_entity="PERSON", name="KnownNameRecognizer", deny_list=parts,
                             global_regex_flags=CASE_SENSITIVE)


def mask(text: str, known_names: list[str] | None = None) -> str:
    """Return a copy of the text with names replaced by [NAME] and phone numbers by [PHONE]."""
    if not text:
        return text
    extra = [known_name_recognizer(known_names)] if known_names else []
    findings = analyzer().analyze(text=text, entities=ENTITIES, language="en", ad_hoc_recognizers=extra)
    operators = {entity: OperatorConfig("replace", {"new_value": placeholder})
                 for entity, placeholder in PLACEHOLDERS.items()}
    return AnonymizerEngine().anonymize(text=text, analyzer_results=findings, operators=operators).text


def mask_keeping_names(text: str) -> tuple[str, list[str]]:
    """Mask a question for the model, and return the names removed, in order.
    The names stay in Python: they are never sent to the model or saved."""
    if not text:
        return text, []
    findings = analyzer().analyze(text=text, entities=ENTITIES, language="en")
    names = [re.sub(rf"^{TITLES}\s+", "", text[f.start:f.end]).strip()       # "Mrs Ama Mensah" -> "Ama Mensah"
             for f in sorted(findings, key=lambda f: f.start) if f.entity_type == "PERSON"]
    return mask(text), [name for name in dict.fromkeys(names) if name]
