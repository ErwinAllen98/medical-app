"""Error taxonomy and cognitive levels for the diagnostic engine."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Error taxonomy (section 5 of the architecture)
# ---------------------------------------------------------------------------

ERROR_TYPES: dict[str, dict[str, str]] = {
    "FACTUAL_ERROR": {
        "label": "Factual",
        "definition": "A discrete fact (name, value, dose, number) is not retrievable or is wrong.",
        "remedy": "Re-encode the atomic fact; split the card if it carries more than one fact.",
    },
    "CONCEPT_ERROR": {
        "label": "Conceptual",
        "definition": "The underlying mechanism / principle is not understood; the fact is memorised but not owned.",
        "remedy": "Return to the source explanation, rebuild the causal chain, then re-test.",
    },
    "DISCRIMINATION_ERROR": {
        "label": "Discrimination",
        "definition": "Two similar entities (drugs, diseases, syndromes) are being confused with each other.",
        "remedy": "Build an explicit A-vs-B contrast table and test with forced-choice items.",
    },
    "EXCEPTION_ERROR": {
        "label": "Exception",
        "definition": "The general rule is known but the exceptions / special populations are not.",
        "remedy": "Study the rule and its exception list together, then test only boundary cases.",
    },
    "THRESHOLD_ERROR": {
        "label": "Threshold",
        "definition": "Numeric cut-offs, ranges or initiation/stopping criteria are unstable.",
        "remedy": "Group all thresholds of the topic into one table; test with just-below / just-above values.",
    },
    "SEQUENCE_ERROR": {
        "label": "Sequence / algorithm",
        "definition": "Steps of a workflow or guideline algorithm are known but mis-ordered.",
        "remedy": "Re-study the algorithm figure; test with ordering and 'what is the next step' items.",
    },
    "INDICATION_ERROR": {
        "label": "Indication",
        "definition": "When to use an intervention is unclear.",
        "remedy": "Study the indication list with its evidence level; test with clinical vignettes.",
    },
    "CONTRAINDICATION_ERROR": {
        "label": "Contraindication",
        "definition": "When NOT to use an intervention (absolute vs relative) is unclear.",
        "remedy": "Study absolute vs relative contraindications side by side; test with trap vignettes.",
    },
    "MONITORING_ERROR": {
        "label": "Monitoring",
        "definition": "What to follow, how often, and what result triggers action is unclear.",
        "remedy": "Build a monitoring schedule table (parameter / timing / action threshold).",
    },
    "MANAGEMENT_ERROR": {
        "label": "Management",
        "definition": "Overall treatment choice or escalation strategy is wrong.",
        "remedy": "Re-study the management algorithm end to end and test with integrated cases.",
    },
}

ERROR_TYPE_KEYS: list[str] = list(ERROR_TYPES)

# Extra failure signatures the diagnostic engine also looks for (section 5).
FAILURE_SIGNATURES: list[str] = [
    "REPEATED_FAILURE",          # same card fails again and again
    "RECURRENT_CONCEPT",         # the same concept fails across different cards
    "SIMILARITY_INTERFERENCE",   # neighbouring knowledge units interfere
    "FALSE_CONFIDENCE",          # fast "Easy" answers followed by lapses
    "MEMORISED_NOT_UNDERSTOOD",  # recall ok, application fails
    "UNDERSTOOD_NOT_RETRIEVABLE",  # application ok, fast recall fails
    "KNOWLEDGE_GAP",             # never answered correctly
]

# ---------------------------------------------------------------------------
# 2. Adaptive cognitive ladder (sections 9 & 10)
# ---------------------------------------------------------------------------

COGNITIVE_LEVELS: dict[int, dict[str, str]] = {
    1: {
        "code": "SOURCE_RECALL",
        "label": "L1 · Source & basic recall",
        "goal": "Re-anchor the fact in the source; single atomic question.",
    },
    2: {
        "code": "CONCEPT",
        "label": "L2 · Concept & mechanism",
        "goal": "Explain why the fact is true; cause-effect chains.",
    },
    3: {
        "code": "DISCRIMINATION",
        "label": "L3 · Discrimination & boundaries",
        "goal": "Distinguish look-alikes, thresholds, exceptions, boundary cases.",
    },
    4: {
        "code": "APPLICATION",
        "label": "L4 · Clinical application",
        "goal": "Short vignette; choose the next best step.",
    },
    5: {
        "code": "INTEGRATION",
        "label": "L5 · Integrated reasoning",
        "goal": "Multi-morbidity cases, conflicting guidance, exceptions inside cases.",
    },
}

# Which cognitive level best attacks each error type.
ERROR_TO_LEVEL: dict[str, int] = {
    "FACTUAL_ERROR": 1,
    "CONCEPT_ERROR": 2,
    "DISCRIMINATION_ERROR": 3,
    "EXCEPTION_ERROR": 3,
    "THRESHOLD_ERROR": 3,
    "SEQUENCE_ERROR": 4,
    "INDICATION_ERROR": 4,
    "CONTRAINDICATION_ERROR": 4,
    "MONITORING_ERROR": 4,
    "MANAGEMENT_ERROR": 5,
}


def describe(error_type: str) -> str:
    info = ERROR_TYPES.get(error_type)
    if not info:
        return error_type
    return f"{error_type} — {info['definition']}"


def level_label(level: int) -> str:
    return COGNITIVE_LEVELS.get(int(level), COGNITIVE_LEVELS[1])["label"]
