"""Generate the OCR test dataset: dummy answers overlaid on the real
MetLife TPD Initial Information Form template pages.

For each of 6 fictional personas, three variants are produced:

    full            - every field filled
    mandatory_only  - mandatory fields (+ one contact) filled, optional blank
    gaps            - mandatory_only, minus 1-2 mandatory fields deliberately
                      left blank (seeded per persona, so runs are reproducible)
                      → exercises the approval gate in the app

Each document is a 2-page PDF (pages 2/10 and 3/10 of the original form -
the pages embedded in the Process Definition Document; conveniently the
Azure free tier OCRs exactly 2 pages per call). Next to every PDF sits a
ground-truth JSON with the values written onto the page and the list of
deliberately-missing fields, so OCR output can later be *scored*, not just
eyeballed.

Usage (from the repo root):

    python scripts/make_dataset.py               # writes dataset/
    python scripts/make_dataset.py --calibrate   # also writes PNG pages for
                                                 # visually checking positions

All data is fictional.
"""

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PAGE1 = ROOT / "docs/templates/metlife-tpd-initial-information-form-p01.jpg"
PAGE2 = ROOT / "docs/templates/metlife-tpd-initial-information-form-p02.jpg"
OUT = ROOT / "dataset"

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
INK = (36, 36, 120)  # pen-blue

# ---------------------------------------------------------------------------
# Where each answer is written, in pixels on the 993x1404 template scans.
# (page, x, y[, font_size]) - tuned by generating a calibration sheet and
# looking at it. "extra" entries are realism-only: drawn on the page but not
# part of the app's extraction schema.
# ---------------------------------------------------------------------------
POSITIONS = {
    # --- page 1 (form page 2/10) ---
    "signature_date":     (1, 720, 330),
    "full_name":          (1, 62, 452),    # extra: declaration print-name line
    "signature_scrawl":   (1, 90, 350),    # extra: fake "signature"
    "member_number":      (1, 62, 578),
    "title":              (1, 66, 638),
    "given_names":        (1, 158, 638),
    "surname":            (1, 62, 696),
    "previous_names":     (1, 512, 696),
    "address_street":     (1, 62, 752),
    "address_suburb":     (1, 512, 752),
    "address_state":      (1, 758, 752),
    "address_postcode":   (1, 842, 752),
    "contact_phone":      (1, 62, 810),
    "email":              (1, 512, 810),
    "gender":             (1, None, 858),  # checkbox - x chosen by value
    "date_of_birth":      (1, 630, 866),
    "diagnosis":          (1, 66, 1155, 14),
    "date_symptoms_commenced": (1, 522, 1160, 13),
    "date_first_consulted":    (1, 660, 1160, 13),
    "date_of_disability":      (1, 812, 1160, 13),
    # --- page 2 (form page 3/10) ---
    "accident_related":   (2, None, 108),  # Yes/No checkboxes
    "date_last_worked":   (2, 800, 243),
    "doctor_name":        (2, 64, 980, 13),
    "doctor_address":     (2, 236, 972, 12),   # extra
    "doctor_specialty":   (2, 455, 980, 13),
    "doctor_date_first":  (2, 602, 985, 13),   # extra
    "doctor_date_last":   (2, 718, 985, 13),   # extra
    "doctor_usual":       (2, 858, 980, 13),   # extra
}
GENDER_X = {"Male": 66, "Female": 180, "Other": 302}
ACCIDENT_X = {"Yes": 826, "No": 888}

MANDATORY = [
    "member_number", "given_names", "surname", "date_of_birth",
    "address_street", "address_suburb", "address_state", "address_postcode",
    "diagnosis", "date_of_disability", "date_last_worked", "signature_date",
]
# In mandatory_only we keep ONE contact (the group rule needs at least one).
CONTACT_KEPT = "contact_phone"
OPTIONAL = [
    "title", "previous_names", "gender", "email",
    "date_symptoms_commenced", "date_first_consulted",
    "accident_related", "doctor_name", "doctor_specialty",
]
EXTRAS_FULL = ["full_name", "signature_scrawl", "doctor_address",
               "doctor_date_first", "doctor_date_last", "doctor_usual"]
EXTRAS_MANDATORY = ["full_name", "signature_scrawl"]

PERSONAS = [
    {
        "slug": "peter-mitchell",
        "title": "Mr", "given_names": "Peter James", "surname": "Mitchell",
        "previous_names": "", "gender": "Male",
        "member_number": "MP-7284915", "date_of_birth": "09/04/1968",
        "address_street": "14 Banksia Crescent", "address_suburb": "Engadine",
        "address_state": "NSW", "address_postcode": "2233",
        "contact_phone": "0412 884 291", "email": "peter.mitchell68@bigpond.com",
        "diagnosis": "Chronic lumbar radiculopathy L4/L5",
        "date_symptoms_commenced": "03/02/2025", "date_first_consulted": "17/02/2025",
        "date_of_disability": "12/05/2025", "date_last_worked": "09/05/2025",
        "signature_date": "01/07/2025", "accident_related": "No",
        "doctor_name": "Dr Susan Hartley", "doctor_specialty": "GP",
        "doctor_address": "Engadine Family Practice, 2 Station St",
        "doctor_date_first": "17/02/2025", "doctor_date_last": "24/06/2025", "doctor_usual": "Yes",
    },
    {
        "slug": "aisha-rahman",
        "title": "Ms", "given_names": "Aisha", "surname": "Rahman",
        "previous_names": "", "gender": "Female",
        "member_number": "MP-5531208", "date_of_birth": "22/11/1979",
        "address_street": "8/155 Lygon Street", "address_suburb": "Brunswick East",
        "address_state": "VIC", "address_postcode": "3057",
        "contact_phone": "0433 019 552", "email": "a.rahman@outlook.com.au",
        "diagnosis": "Multiple sclerosis, relapsing-remitting",
        "date_symptoms_commenced": "10/09/2024", "date_first_consulted": "02/10/2024",
        "date_of_disability": "18/03/2025", "date_last_worked": "14/03/2025",
        "signature_date": "22/06/2025", "accident_related": "No",
        "doctor_name": "Dr Marcus Chen", "doctor_specialty": "Neurologist",
        "doctor_address": "Royal Melbourne Hospital, Parkville",
        "doctor_date_first": "02/10/2024", "doctor_date_last": "30/05/2025", "doctor_usual": "No",
    },
    {
        "slug": "daniel-oconnor",
        "title": "Mr", "given_names": "Daniel Francis", "surname": "O'Connor",
        "previous_names": "", "gender": "Male",
        "member_number": "MP-9902174", "date_of_birth": "31/01/1962",
        "address_street": "77 Ipswich Road", "address_suburb": "Woolloongabba",
        "address_state": "QLD", "address_postcode": "4102",
        "contact_phone": "0401 776 348", "email": "danoconnor62@gmail.com",
        "diagnosis": "Severe osteoarthritis, both knees",
        "date_symptoms_commenced": "05/06/2023", "date_first_consulted": "21/08/2023",
        "date_of_disability": "02/02/2025", "date_last_worked": "31/01/2025",
        "signature_date": "15/06/2025", "accident_related": "No",
        "doctor_name": "Dr Priya Nair", "doctor_specialty": "Orthopaedic surgeon",
        "doctor_address": "Brisbane Orthopaedic Group, Stones Corner",
        "doctor_date_first": "21/08/2023", "doctor_date_last": "12/06/2025", "doctor_usual": "No",
    },
    {
        "slug": "mei-lin-chen",
        "title": "Mrs", "given_names": "Mei Lin", "surname": "Chen",
        "previous_names": "Mei Lin Wong", "gender": "Female",
        "member_number": "MP-3317840", "date_of_birth": "17/07/1974",
        "address_street": "23 Waratah Avenue", "address_suburb": "Glen Waverley",
        "address_state": "VIC", "address_postcode": "3150",
        "contact_phone": "0422 640 187", "email": "meilin.chen74@yahoo.com",
        "diagnosis": "Rheumatoid arthritis, seropositive",
        "date_symptoms_commenced": "12/01/2024", "date_first_consulted": "29/01/2024",
        "date_of_disability": "07/04/2025", "date_last_worked": "04/04/2025",
        "signature_date": "30/06/2025", "accident_related": "No",
        "doctor_name": "Dr Alan Kostas", "doctor_specialty": "Rheumatologist",
        "doctor_address": "Monash Medical Centre, Clayton",
        "doctor_date_first": "29/01/2024", "doctor_date_last": "20/06/2025", "doctor_usual": "No",
    },
    {
        "slug": "grace-waqa",
        "title": "Ms", "given_names": "Grace Talei", "surname": "Waqa",
        "previous_names": "", "gender": "Female",
        "member_number": "MP-6648032", "date_of_birth": "03/12/1985",
        "address_street": "5 Kurrajong Place", "address_suburb": "Blacktown",
        "address_state": "NSW", "address_postcode": "2148",
        "contact_phone": "0455 208 913", "email": "grace.waqa@hotmail.com",
        "diagnosis": "Major depressive disorder, treatment-resistant",
        "date_symptoms_commenced": "20/03/2024", "date_first_consulted": "11/04/2024",
        "date_of_disability": "25/02/2025", "date_last_worked": "21/02/2025",
        "signature_date": "18/06/2025", "accident_related": "No",
        "doctor_name": "Dr Helen Broderick", "doctor_specialty": "Psychiatrist",
        "doctor_address": "Westmead Psychiatry Clinic",
        "doctor_date_first": "11/04/2024", "doctor_date_last": "10/06/2025", "doctor_usual": "No",
    },
    {
        "slug": "stefan-kovac",
        "title": "Mr", "given_names": "Stefan", "surname": "Kovac",
        "previous_names": "", "gender": "Male",
        "member_number": "MP-1149763", "date_of_birth": "26/08/1959",
        "address_street": "112 Seaview Terrace", "address_suburb": "Glenelg North",
        "address_state": "SA", "address_postcode": "5045",
        "contact_phone": "0409 335 671", "email": "skovac59@internode.on.net",
        "diagnosis": "Cervical spondylotic myelopathy",
        "date_symptoms_commenced": "14/10/2024", "date_first_consulted": "05/11/2024",
        "date_of_disability": "30/04/2025", "date_last_worked": "28/04/2025",
        "signature_date": "10/07/2025", "accident_related": "Yes",
        "doctor_name": "Dr James Whitford", "doctor_specialty": "Neurosurgeon",
        "doctor_address": "Flinders Medical Centre, Bedford Park",
        "doctor_date_first": "05/11/2024", "doctor_date_last": "01/07/2025", "doctor_usual": "No",
    },
]


def draw_value(draw: ImageDraw.ImageDraw, page_num: int, key: str, value: str) -> None:
    pos = POSITIONS[key]
    if pos[0] != page_num or not value:
        return
    size = pos[3] if len(pos) > 3 else 15
    font = ImageFont.truetype(FONT_PATH, size)
    if key == "gender":
        draw.text((GENDER_X.get(value, GENDER_X["Other"]), pos[2]), "X", fill=INK,
                  font=ImageFont.truetype(FONT_PATH, 15))
    elif key == "accident_related":
        draw.text((ACCIDENT_X.get(value, ACCIDENT_X["No"]), pos[2]), "X", fill=INK,
                  font=ImageFont.truetype(FONT_PATH, 15))
    elif key == "signature_scrawl":
        # A cursive-ish scrawl stand-in; italic to look signature-like.
        italic = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Italic.ttf", 22)
        draw.text((pos[1], pos[2]), value, fill=INK, font=italic)
    else:
        draw.text((pos[1], pos[2]), value, fill=INK, font=font)


def fields_for_variant(persona: dict, variant: str, rng: random.Random):
    """Return (fields_to_draw, deliberately_missing) for one document."""
    if variant == "full":
        keys = MANDATORY + [CONTACT_KEPT] + OPTIONAL
        missing = []
        extras = EXTRAS_FULL
    elif variant == "mandatory_only":
        keys = MANDATORY + [CONTACT_KEPT]
        missing = []
        extras = EXTRAS_MANDATORY
    elif variant == "gaps":
        dropped = rng.sample(MANDATORY, rng.choice([1, 2]))
        keys = [k for k in MANDATORY if k not in dropped] + [CONTACT_KEPT]
        missing = dropped
        extras = EXTRAS_MANDATORY if "signature_date" not in dropped else []
    else:
        raise ValueError(variant)

    fields = {k: persona[k] for k in keys}
    for extra in extras:
        if extra == "full_name":
            fields["full_name"] = f"{persona['given_names']} {persona['surname']}"
        elif extra == "signature_scrawl":
            fields["signature_scrawl"] = f"{persona['given_names'].split()[0]} {persona['surname']}"
        else:
            fields[extra] = persona[extra]
    return fields, missing


def render_document(fields: dict) -> tuple[Image.Image, Image.Image]:
    pages = []
    for page_num, path in [(1, PAGE1), (2, PAGE2)]:
        img = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(img)
        for key, value in fields.items():
            draw_value(draw, page_num, key, value)
        pages.append(img)
    return pages[0], pages[1]


def main() -> None:
    calibrate = "--calibrate" in sys.argv
    OUT.mkdir(exist_ok=True)
    manifest = []

    for i, persona in enumerate(PERSONAS):
        rng = random.Random(i)  # per-persona seed → reproducible gaps
        for variant in ["full", "mandatory_only", "gaps"]:
            fields, missing = fields_for_variant(persona, variant, rng)
            p1, p2 = render_document(fields)

            stem = f"metlife-tpd_{persona['slug']}_{variant}"
            p1.save(OUT / f"{stem}.pdf", save_all=True, append_images=[p2])

            # Ground truth: schema fields only (extras are page realism).
            schema_keys = MANDATORY + [CONTACT_KEPT] + OPTIONAL
            truth = {
                "file": f"{stem}.pdf",
                "persona": persona["slug"],
                "variant": variant,
                "deliberately_missing": missing,
                "fields": {k: fields.get(k) or None for k in schema_keys},
            }
            (OUT / f"{stem}.json").write_text(json.dumps(truth, indent=2))
            manifest.append(truth)

            if calibrate and i == 0 and variant == "full":
                p1.save(OUT / "_calibration_p1.png")
                p2.save(OUT / "_calibration_p2.png")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(manifest)} documents (+ ground truth) to {OUT}")


if __name__ == "__main__":
    main()
