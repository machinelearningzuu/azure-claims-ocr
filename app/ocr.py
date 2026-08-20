"""OCR interface — the AI step.

The rest of the app only knows one function:

    extract_fields(document_bytes, template) -> [{name, value, confidence}]

Behind it sits Azure Document Intelligence's "prebuilt-document" model, which
returns generic key/value pairs it found on the page (e.g. "Date of birth:"
→ "12/03/1975"), each with a confidence score. We then map those raw pairs
onto the template's field specs using their synonym phrases.

Why confidence matters here: the score is the model telling us how sure it
is. We pass it through untouched so the review layer can route low-confidence
fields to the human's attention. The OCR layer PROPOSES — it never decides.
"""

import re

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from app import config
from app.models import DEFAULT_TEMPLATE, template_fields


def _normalize(label: str) -> str:
    """Lowercase, strip punctuation, and collapse runs of whitespace so
    'Date of Birth (dd/mm/yyyy):' matches 'date of birth dd mm yyyy'."""
    cleaned = re.sub(r"[^a-z0-9 ]", " ", label.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _get_client() -> DocumentAnalysisClient:
    return DocumentAnalysisClient(
        endpoint=config.AZURE_DOCINTEL_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_DOCINTEL_KEY),
    )


def match_raw_pairs(raw_pairs: list[tuple], template: str) -> list[dict]:
    """Map raw OCR key/value pairs onto the template's fields. Pure function —
    no network, no Azure — so it is unit-testable in CI, where no OCR
    credentials exist. `raw_pairs` is [(normalized_label, value, confidence)].
    """
    fields = []
    for spec in template_fields(template):
        # Best match wins. Score = (synonym length, confidence): a longer
        # matched phrase is more specific — "date of birth" must beat a
        # stray match on just "date" — and confidence breaks ties.
        best_value, best_confidence, best_score = None, 0.0, (0, 0.0)
        for label, value, confidence in raw_pairs:
            for phrase in spec.synonyms:
                if phrase in label:
                    score = (len(phrase), confidence)
                    if score > best_score:
                        best_value, best_confidence, best_score = value, confidence, score
        fields.append(
            {"name": spec.name, "value": best_value, "confidence": round(best_confidence, 4)}
        )
    return fields


def extract_fields(document_bytes: bytes, template: str = DEFAULT_TEMPLATE) -> list[dict]:
    """Run real Azure OCR on the document and return the template's fields.

    Every field in the template is always returned, in spec order. A field
    the OCR couldn't find comes back with value=None and confidence=0.0 —
    the human review screen always shows the complete picture, including
    what the AI *failed* to find, instead of silently dropping fields.
    """
    client = _get_client()
    poller = client.begin_analyze_document("prebuilt-document", document=document_bytes)
    result = poller.result()

    # Every key/value pair the model found: (normalized label, value, confidence)
    raw_pairs = []
    for kv in result.key_value_pairs:
        if kv.key is None or kv.value is None:
            continue
        raw_pairs.append(
            (_normalize(kv.key.content), kv.value.content.strip(), kv.confidence or 0.0)
        )

    return match_raw_pairs(raw_pairs, template)
