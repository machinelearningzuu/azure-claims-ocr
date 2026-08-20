"""Generate a fake superannuation claim form as a PDF, so you have a
realistic document to upload on your first test run.

Usage (from the repo root, venv active):

    python scripts/make_sample_claim.py

Writes ./sample_claim.pdf — all data is fictional.
"""

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

FIELDS = [
    ("Member Name", "Margaret Ellen Whitfield"),
    ("Member Number", "SF-4471962"),
    ("Date of Birth", "14/03/1971"),
    ("Date of Disability", "02/11/2025"),
    ("Diagnosis", "Chronic lumbar radiculopathy"),
    ("Occupation", "Warehouse Team Leader"),
    ("Employer", "Southern Cross Logistics Pty Ltd"),
    ("Account Balance", "$184,250.75"),
    ("Insurer", "MetSafe Life Insurance Ltd"),
]


def main() -> None:
    pdf = canvas.Canvas("sample_claim.pdf", pagesize=A4)
    width, height = A4

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(60, height - 70, "Total & Permanent Disability Claim Form")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(60, height - 90, "Section A — Member and Claim Details (sample document, fictional data)")

    y = height - 140
    for label, value in FIELDS:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(60, y, f"{label}:")
        pdf.setFont("Helvetica", 11)
        pdf.drawString(220, y, value)
        y -= 34

    pdf.save()
    print("Wrote sample_claim.pdf")


if __name__ == "__main__":
    main()
