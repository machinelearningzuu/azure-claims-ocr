"""The services layer: every external dependency lives behind its own small
service module with a stable interface, so the app logic in main.py never
cares which implementation is plugged in.

    ocr_service    the AI/extraction step (Azure Document Intelligence today;
                   could be any OCR engine or an LLM extractor tomorrow)
    queue_service  the pending-review queue (in-process today; Azure Service
                   Bus in Layer 3)
    db_service     committed, human-approved claims (SQLite today; Azure
                   PostgreSQL in Layer 2)

Swapping an implementation means editing one file in this package. Nothing
outside it changes.
"""
