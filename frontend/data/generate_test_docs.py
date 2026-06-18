"""
Generate mock medical documents for ClaimPilot test cases.
Run from the project root:
    python frontend/data/generate_test_docs.py

Outputs three formats per document into frontend/data/test_docs/{TC00X}/:
  prescription.jpg        — JPEG image (photographed document)
  prescription.pdf        — scanned PDF (image wrapped in PDF)
  prescription_text.pdf   — text PDF (selectable text, digitally created)
"""
from pathlib import Path
from textwrap import wrap

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent / "test_docs"

# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _font(size: int = 14):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _new_doc(width: int = 800, height: int = 1000) -> tuple[Image.Image, ImageDraw.Draw]:
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Subtle border
    draw.rectangle([10, 10, width - 10, height - 10], outline=(180, 180, 180), width=1)
    return img, draw


def _header(draw: ImageDraw.Draw, title: str, subtitle: str = "", y: int = 30) -> int:
    draw.text((40, y), title, fill=(20, 20, 120), font=_font(20))
    y += 28
    if subtitle:
        draw.text((40, y), subtitle, fill=(80, 80, 80), font=_font(13))
        y += 20
    draw.line([(40, y + 4), (760, y + 4)], fill=(180, 180, 180), width=1)
    return y + 18


def _row(draw: ImageDraw.Draw, label: str, value: str, y: int, label_w: int = 220) -> int:
    draw.text((40, y), label, fill=(100, 100, 100), font=_font(13))
    draw.text((40 + label_w, y), value, fill=(20, 20, 20), font=_font(13))
    return y + 22


def _section(draw: ImageDraw.Draw, title: str, y: int) -> int:
    y += 8
    draw.rectangle([40, y, 760, y + 22], fill=(240, 244, 255))
    draw.text((46, y + 4), title.upper(), fill=(40, 40, 120), font=_font(12))
    return y + 30


def _table_header(draw: ImageDraw.Draw, cols: list[tuple[int, str]], y: int) -> int:
    draw.rectangle([40, y, 760, y + 24], fill=(220, 230, 255))
    for x, label in cols:
        draw.text((x, y + 5), label, fill=(20, 20, 80), font=_font(12))
    return y + 28


def _table_row(draw: ImageDraw.Draw, cols: list[tuple[int, str]], y: int, shade: bool = False) -> int:
    if shade:
        draw.rectangle([40, y, 760, y + 22], fill=(248, 248, 255))
    for x, val in cols:
        draw.text((x, y + 4), val, fill=(30, 30, 30), font=_font(12))
    return y + 24


def _stamp(draw: ImageDraw.Draw, text: str, x: int, y: int):
    draw.ellipse([x, y, x + 120, y + 50], outline=(180, 40, 40), width=2)
    draw.text((x + 10, y + 16), text, fill=(180, 40, 40), font=_font(11))


def _save(img: Image.Image, tc_id: str, fname: str):
    d = OUT_DIR / tc_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / fname
    img.save(path, "JPEG", quality=90)
    print(f"  saved: {path.relative_to(OUT_DIR.parent.parent)}")

    # Scanned PDF: same image wrapped inside a PDF (no selectable text)
    pdf_path = path.with_suffix(".pdf")
    img.save(pdf_path, "PDF", resolution=150)
    print(f"  saved: {pdf_path.relative_to(OUT_DIR.parent.parent)}")


# ---------------------------------------------------------------------------
# Text PDF helpers (fpdf2 — selectable text, digitally created documents)
# ---------------------------------------------------------------------------

def _l(text: str) -> str:
    """Sanitise text for fpdf2 latin-1 Helvetica: replace characters outside latin-1."""
    return (
        text
        .replace("—", "-")   # em dash
        .replace("–", "-")   # en dash
        .replace("₹", "Rs.") # rupee sign
        .replace("’", "'")   # right single quote
        .replace("‘", "'")   # left single quote
        .replace("“", '"')   # left double quote
        .replace("”", '"')   # right double quote
    )


def _pdf_base(title: str, subtitle: str = "") -> FPDF:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _l(title), new_x="LMARGIN", new_y="NEXT")
    if subtitle:
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 6, _l(subtitle), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(15, pdf.get_y() + 2, 195, pdf.get_y() + 2)
    pdf.ln(6)
    return pdf


def _pdf_section(pdf: FPDF, title: str) -> None:
    pdf.ln(2)
    pdf.set_fill_color(240, 244, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, f"  {_l(title).upper()}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.ln(1)


def _pdf_row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(55, 6, _l(label))
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, _l(value), new_x="LMARGIN", new_y="NEXT")


def _pdf_save(pdf: FPDF, tc_id: str, stem: str) -> None:
    d = OUT_DIR / tc_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{stem}_text.pdf"
    pdf.output(str(path))
    print(f"  saved: {path.relative_to(OUT_DIR.parent.parent)}")


def _text_pdf_prescription(
    tc_id: str, stem: str, doctor: str, reg: str, patient: str,
    date_str: str, diagnosis: str, medicines: list[str], tests: list[str] | None = None,
) -> None:
    pdf = _pdf_base(f"Dr. {doctor}", f"Reg. No: {reg}  |  City Medical Centre, Bengaluru")
    _pdf_section(pdf, "Patient Details")
    _pdf_row(pdf, "Patient Name:", patient)
    _pdf_row(pdf, "Date:", date_str)
    _pdf_row(pdf, "Diagnosis:", diagnosis)
    _pdf_section(pdf, "Prescription (Rx)")
    for i, med in enumerate(medicines, 1):
        pdf.set_font("Helvetica", size=11)
        pdf.cell(0, 6, _l(f"  {i}. {med}"), new_x="LMARGIN", new_y="NEXT")
    if tests:
        _pdf_section(pdf, "Investigations Ordered")
        for t in tests:
            pdf.set_font("Helvetica", size=11)
            pdf.cell(0, 6, _l(f"  - {t}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Digitally signed - Dr. Stamp & Signature on file", new_x="LMARGIN", new_y="NEXT")
    _pdf_save(pdf, tc_id, stem)


def _text_pdf_hospital_bill(
    tc_id: str, stem: str, hospital: str, patient: str,
    date_str: str, items: list[tuple[str, float]],
) -> None:
    pdf = _pdf_base(hospital, "BILL / RECEIPT")
    _pdf_section(pdf, "Patient Details")
    _pdf_row(pdf, "Patient Name:", patient)
    _pdf_row(pdf, "Date:", date_str)
    _pdf_section(pdf, "Itemized Bill")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(220, 230, 255)
    pdf.cell(140, 7, "DESCRIPTION", fill=True)
    pdf.cell(0, 7, "AMOUNT (Rs.)", fill=True, new_x="LMARGIN", new_y="NEXT")
    total = 0.0
    for i, (desc, amt) in enumerate(items):
        pdf.set_font("Helvetica", size=10)
        pdf.set_fill_color(248, 248, 255) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.cell(140, 6, _l(f"  {desc}"), fill=True)
        pdf.cell(0, 6, f"{amt:,.2f}", fill=True, new_x="LMARGIN", new_y="NEXT")
        total += amt
    pdf.ln(2)
    pdf.set_draw_color(160, 160, 160)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(140, 7, "TOTAL")
    pdf.set_text_color(20, 20, 120)
    pdf.cell(0, 7, f"Rs. {total:,.2f}", new_x="LMARGIN", new_y="NEXT")
    _pdf_save(pdf, tc_id, stem)


def _text_pdf_pharmacy_bill(
    tc_id: str, stem: str, patient: str, date_str: str, items: list[tuple[str, float]],
) -> None:
    pdf = _pdf_base("Health First Pharmacy", "Drug Lic. No: KA-BLR-XXXX  |  Brigade Road, Bengaluru")
    _pdf_section(pdf, "Bill Details")
    _pdf_row(pdf, "Patient:", patient)
    _pdf_row(pdf, "Date:", date_str)
    _pdf_section(pdf, "Medicines")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(220, 230, 255)
    pdf.cell(140, 7, "MEDICINE", fill=True)
    pdf.cell(0, 7, "AMOUNT (Rs.)", fill=True, new_x="LMARGIN", new_y="NEXT")
    total = 0.0
    for i, (med, amt) in enumerate(items):
        pdf.set_font("Helvetica", size=10)
        pdf.set_fill_color(248, 248, 255) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.cell(140, 6, _l(f"  {med}"), fill=True)
        pdf.cell(0, 6, f"{amt:,.2f}", fill=True, new_x="LMARGIN", new_y="NEXT")
        total += amt
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(20, 20, 120)
    pdf.cell(0, 7, f"Net Amount: Rs. {total:,.2f}", new_x="LMARGIN", new_y="NEXT")
    _pdf_save(pdf, tc_id, stem)


def _text_pdf_lab_report(
    tc_id: str, stem: str, patient: str, test_name: str, date_str: str,
) -> None:
    pdf = _pdf_base("Precision Diagnostics Pvt Ltd", "NABL Accredited Lab  |  Jayanagar, Bengaluru")
    _pdf_section(pdf, "Patient Details")
    _pdf_row(pdf, "Patient:", patient)
    _pdf_row(pdf, "Report Date:", date_str)
    _pdf_section(pdf, "Test Report")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _l(test_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(220, 230, 255)
    pdf.cell(80, 7, "TEST", fill=True)
    pdf.cell(60, 7, "RESULT", fill=True)
    pdf.cell(0, 7, "NORMAL RANGE", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(80, 6, _l(test_name))
    pdf.cell(60, 6, "See report")
    pdf.cell(0, 6, "-", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, "Clinical correlation advised.", new_x="LMARGIN", new_y="NEXT")
    _pdf_save(pdf, tc_id, stem)


# ---------------------------------------------------------------------------
# Document generators
# ---------------------------------------------------------------------------

def prescription(
    tc_id: str,
    fname: str,
    doctor: str,
    reg: str,
    patient: str,
    date_str: str,
    diagnosis: str,
    medicines: list[str],
    tests: list[str] | None = None,
    blurry: bool = False,
):
    img, draw = _new_doc()
    y = _header(draw, f"Dr. {doctor}", f"Reg. No: {reg}  |  City Medical Centre, Bengaluru")
    y = _section(draw, "Patient Details", y)
    y = _row(draw, "Patient Name:", patient, y)
    y = _row(draw, "Date:", date_str, y)
    y = _row(draw, "Diagnosis:", diagnosis, y)
    y = _section(draw, "Prescription (Rx)", y)
    for i, med in enumerate(medicines, 1):
        draw.text((60, y), f"{i}. {med}", fill=(20, 20, 20), font=_font(13))
        y += 22
    if tests:
        y = _section(draw, "Investigations Ordered", y)
        for t in tests:
            draw.text((60, y), f"• {t}", fill=(20, 20, 20), font=_font(13))
            y += 22
    _stamp(draw, "Dr Stamp", 580, 860)
    draw.text((580, 920), "Signature", fill=(100, 100, 100), font=_font(11))

    if blurry:
        import cv2, numpy as np
        arr = np.array(img)
        arr = cv2.GaussianBlur(arr, (25, 25), 0)
        img = Image.fromarray(arr)

    _save(img, tc_id, fname)


def hospital_bill(
    tc_id: str,
    fname: str,
    hospital: str,
    patient: str,
    date_str: str,
    items: list[tuple[str, float]],
    blurry: bool = False,
):
    img, draw = _new_doc()
    y = _header(draw, hospital, "BILL / RECEIPT")
    y = _section(draw, "Patient Details", y)
    y = _row(draw, "Patient Name:", patient, y)
    y = _row(draw, "Date:", date_str, y)
    y = _section(draw, "Itemized Bill", y)
    cols_h = [(46, "DESCRIPTION"), (560, "AMOUNT (₹)")]
    y = _table_header(draw, cols_h, y)
    total = 0.0
    for i, (desc, amt) in enumerate(items):
        y = _table_row(draw, [(46, desc), (560, f"{amt:,.2f}")], y, shade=i % 2 == 0)
        total += amt
    draw.line([(40, y + 4), (760, y + 4)], fill=(160, 160, 160), width=1)
    y += 12
    draw.text((460, y), "TOTAL:", fill=(20, 20, 20), font=_font(14))
    draw.text((560, y), f"₹ {total:,.2f}", fill=(20, 20, 120), font=_font(14))
    _stamp(draw, "PAID", 580, 860)

    if blurry:
        import cv2, numpy as np
        arr = np.array(img)
        arr = cv2.GaussianBlur(arr, (25, 25), 0)
        img = Image.fromarray(arr)

    _save(img, tc_id, fname)


def pharmacy_bill(
    tc_id: str,
    fname: str,
    patient: str,
    date_str: str,
    items: list[tuple[str, float]],
    blurry: bool = False,
):
    img, draw = _new_doc(height=700)
    y = _header(draw, "Health First Pharmacy", "Drug Lic. No: KA-BLR-XXXX  |  Brigade Road, Bengaluru")
    y = _section(draw, "Bill Details", y)
    y = _row(draw, "Patient:", patient, y)
    y = _row(draw, "Date:", date_str, y)
    y = _section(draw, "Medicines", y)
    cols_h = [(46, "MEDICINE"), (500, "AMOUNT (₹)")]
    y = _table_header(draw, cols_h, y)
    total = 0.0
    for i, (med, amt) in enumerate(items):
        y = _table_row(draw, [(46, med), (500, f"{amt:,.2f}")], y, shade=i % 2 == 0)
        total += amt
    y += 10
    draw.text((400, y), f"Net Amount: ₹ {total:,.2f}", fill=(20, 20, 120), font=_font(14))

    if blurry:
        import cv2, numpy as np
        arr = np.array(img)
        arr = cv2.GaussianBlur(arr, (25, 25), 0)
        img = Image.fromarray(arr)

    _save(img, tc_id, fname)


def lab_report(tc_id: str, fname: str, patient: str, test_name: str, date_str: str):
    img, draw = _new_doc()
    y = _header(draw, "Precision Diagnostics Pvt Ltd", "NABL Accredited Lab  |  Jayanagar, Bengaluru")
    y = _section(draw, "Patient Details", y)
    y = _row(draw, "Patient:", patient, y)
    y = _row(draw, "Report Date:", date_str, y)
    y = _section(draw, "Test Report", y)
    draw.text((46, y), test_name, fill=(20, 20, 20), font=_font(14))
    y += 28
    cols_h = [(46, "TEST"), (300, "RESULT"), (480, "NORMAL RANGE")]
    y = _table_header(draw, cols_h, y)
    y = _table_row(draw, [(46, test_name), (300, "See report"), (480, "—")], y)
    draw.text((46, y + 20), "Clinical correlation advised.", fill=(80, 80, 80), font=_font(12))
    _stamp(draw, "Lab Stamp", 580, 860)
    _save(img, tc_id, fname)


# ---------------------------------------------------------------------------
# Generate all test case documents
# ---------------------------------------------------------------------------

def main():
    print("Generating mock test documents (JPEG + scanned PDF + text PDF)…\n")

    # TC001 — two prescriptions (wrong doc type)
    prescription("TC001", "dr_sharma_prescription.jpg", "Arun Sharma", "KA/45678/2015",
                 "Rajesh Kumar", "01-Nov-2024", "Viral Fever",
                 ["Tab Paracetamol 650mg — 1-1-1 x 5 days", "Tab Vitamin C 500mg — 0-0-1 x 7 days"])
    _text_pdf_prescription("TC001", "dr_sharma_prescription", "Arun Sharma", "KA/45678/2015",
                           "Rajesh Kumar", "01-Nov-2024", "Viral Fever",
                           ["Tab Paracetamol 650mg — 1-1-1 x 5 days", "Tab Vitamin C 500mg — 0-0-1 x 7 days"])
    prescription("TC001", "another_prescription.jpg", "B. Rao", "KA/99999/2018",
                 "Rajesh Kumar", "01-Nov-2024", "Viral Fever", ["Ibuprofen 400mg"])
    _text_pdf_prescription("TC001", "another_prescription", "B. Rao", "KA/99999/2018",
                           "Rajesh Kumar", "01-Nov-2024", "Viral Fever", ["Ibuprofen 400mg"])

    # TC002 — prescription (good) + blurry pharmacy bill
    # Note: blur test only meaningful for images; PDF modes skip blur_gate
    prescription("TC002", "prescription.jpg", "Sunil Mehta", "GJ/11111/2016",
                 "Sneha Reddy", "25-Oct-2024", "Seasonal Allergy", ["Cetirizine 10mg — 0-0-1"])
    _text_pdf_prescription("TC002", "prescription", "Sunil Mehta", "GJ/11111/2016",
                           "Sneha Reddy", "25-Oct-2024", "Seasonal Allergy", ["Cetirizine 10mg — 0-0-1"])
    pharmacy_bill("TC002", "blurry_bill.jpg", "Sneha Reddy", "25-Oct-2024",
                  [("Cetirizine 10mg x10", 80.0), ("Vitamin C x5", 50.0)], blurry=True)
    _text_pdf_pharmacy_bill("TC002", "blurry_bill", "Sneha Reddy", "25-Oct-2024",
                            [("Cetirizine 10mg x10", 80.0), ("Vitamin C x5", 50.0)])

    # TC003 — mismatched patients
    prescription("TC003", "prescription_rajesh.jpg", "Arun Sharma", "KA/45678/2015",
                 "Rajesh Kumar", "01-Nov-2024", "Viral Fever", ["Paracetamol 650mg"])
    _text_pdf_prescription("TC003", "prescription_rajesh", "Arun Sharma", "KA/45678/2015",
                           "Rajesh Kumar", "01-Nov-2024", "Viral Fever", ["Paracetamol 650mg"])
    hospital_bill("TC003", "bill_arjun.jpg", "City Clinic", "Arjun Mehta",
                  "01-Nov-2024", [("Consultation Fee", 1000.0)])
    _text_pdf_hospital_bill("TC003", "bill_arjun", "City Clinic", "Arjun Mehta",
                            "01-Nov-2024", [("Consultation Fee", 1000.0)])

    # TC004 — clean consultation
    prescription("TC004", "prescription.jpg", "Arun Sharma", "KA/45678/2015",
                 "Rajesh Kumar", "01-Nov-2024", "Viral Fever",
                 ["Tab Paracetamol 650mg", "Tab Vitamin C 500mg"], tests=["CBC", "Dengue NS1"])
    _text_pdf_prescription("TC004", "prescription", "Arun Sharma", "KA/45678/2015",
                           "Rajesh Kumar", "01-Nov-2024", "Viral Fever",
                           ["Tab Paracetamol 650mg", "Tab Vitamin C 500mg"], tests=["CBC", "Dengue NS1"])
    hospital_bill("TC004", "hospital_bill.jpg", "City Clinic, Bengaluru", "Rajesh Kumar", "01-Nov-2024",
                  [("Consultation Fee (OPD)", 1000.0), ("CBC Test", 300.0), ("Dengue NS1 Test", 200.0)])
    _text_pdf_hospital_bill("TC004", "hospital_bill", "City Clinic, Bengaluru", "Rajesh Kumar", "01-Nov-2024",
                            [("Consultation Fee (OPD)", 1000.0), ("CBC Test", 300.0), ("Dengue NS1 Test", 200.0)])

    # TC005 — diabetes waiting period
    prescription("TC005", "prescription.jpg", "Sunil Mehta", "GJ/56789/2014",
                 "Vikram Joshi", "15-Oct-2024", "Type 2 Diabetes Mellitus",
                 ["Metformin 500mg", "Glimepiride 1mg"])
    _text_pdf_prescription("TC005", "prescription", "Sunil Mehta", "GJ/56789/2014",
                           "Vikram Joshi", "15-Oct-2024", "Type 2 Diabetes Mellitus",
                           ["Metformin 500mg", "Glimepiride 1mg"])
    hospital_bill("TC005", "hospital_bill.jpg", "Apollo Hospital", "Vikram Joshi",
                  "15-Oct-2024", [("Diabetic Consultation", 2000.0), ("HbA1c Test", 1000.0)])
    _text_pdf_hospital_bill("TC005", "hospital_bill", "Apollo Hospital", "Vikram Joshi",
                            "15-Oct-2024", [("Diabetic Consultation", 2000.0), ("HbA1c Test", 1000.0)])

    # TC006 — dental partial
    hospital_bill("TC006", "hospital_bill.jpg", "Smile Dental Clinic", "Priya Singh",
                  "15-Oct-2024", [("Root Canal Treatment", 8000.0), ("Teeth Whitening", 4000.0)])
    _text_pdf_hospital_bill("TC006", "hospital_bill", "Smile Dental Clinic", "Priya Singh",
                            "15-Oct-2024", [("Root Canal Treatment", 8000.0), ("Teeth Whitening", 4000.0)])

    # TC007 — MRI without pre-auth
    prescription("TC007", "prescription.jpg", "Venkat Rao", "AP/67890/2017",
                 "Suresh Patil", "02-Nov-2024", "Suspected Lumbar Disc Herniation",
                 [], tests=["MRI Lumbar Spine"])
    _text_pdf_prescription("TC007", "prescription", "Venkat Rao", "AP/67890/2017",
                           "Suresh Patil", "02-Nov-2024", "Suspected Lumbar Disc Herniation",
                           [], tests=["MRI Lumbar Spine"])
    lab_report("TC007", "lab_report.jpg", "Suresh Patil", "MRI Lumbar Spine", "02-Nov-2024")
    _text_pdf_lab_report("TC007", "lab_report", "Suresh Patil", "MRI Lumbar Spine", "02-Nov-2024")
    hospital_bill("TC007", "hospital_bill.jpg", "Diagnostic Centre", "Suresh Patil",
                  "02-Nov-2024", [("MRI Lumbar Spine", 15000.0)])
    _text_pdf_hospital_bill("TC007", "hospital_bill", "Diagnostic Centre", "Suresh Patil",
                            "02-Nov-2024", [("MRI Lumbar Spine", 15000.0)])

    # TC008 — per-claim limit exceeded
    prescription("TC008", "prescription.jpg", "R. Gupta", "DL/34567/2016",
                 "Amit Verma", "20-Oct-2024", "Gastroenteritis", ["Antibiotics", "Probiotics", "ORS"])
    _text_pdf_prescription("TC008", "prescription", "R. Gupta", "DL/34567/2016",
                           "Amit Verma", "20-Oct-2024", "Gastroenteritis", ["Antibiotics", "Probiotics", "ORS"])
    hospital_bill("TC008", "hospital_bill.jpg", "City Hospital", "Amit Verma",
                  "20-Oct-2024", [("Consultation Fee", 2000.0), ("Medicines", 5500.0)])
    _text_pdf_hospital_bill("TC008", "hospital_bill", "City Hospital", "Amit Verma",
                            "20-Oct-2024", [("Consultation Fee", 2000.0), ("Medicines", 5500.0)])

    # TC009 — fraud: multiple same-day claims
    prescription("TC009", "prescription.jpg", "S. Khan", "MH/12345/2015",
                 "Ravi Menon", "30-Oct-2024", "Migraine", ["Sumatriptan 50mg"])
    _text_pdf_prescription("TC009", "prescription", "S. Khan", "MH/12345/2015",
                           "Ravi Menon", "30-Oct-2024", "Migraine", ["Sumatriptan 50mg"])
    hospital_bill("TC009", "hospital_bill.jpg", "City Clinic D", "Ravi Menon",
                  "30-Oct-2024", [("Consultation Fee", 4800.0)])
    _text_pdf_hospital_bill("TC009", "hospital_bill", "City Clinic D", "Ravi Menon",
                            "30-Oct-2024", [("Consultation Fee", 4800.0)])

    # TC010 — network hospital
    prescription("TC010", "prescription.jpg", "S. Iyer", "TN/56789/2013",
                 "Deepak Shah", "03-Nov-2024", "Acute Bronchitis",
                 ["Amoxicillin 500mg", "Salbutamol Inhaler"])
    _text_pdf_prescription("TC010", "prescription", "S. Iyer", "TN/56789/2013",
                           "Deepak Shah", "03-Nov-2024", "Acute Bronchitis",
                           ["Amoxicillin 500mg", "Salbutamol Inhaler"])
    hospital_bill("TC010", "hospital_bill.jpg", "Apollo Hospitals", "Deepak Shah",
                  "03-Nov-2024", [("Consultation Fee", 1500.0), ("Medicines", 3000.0)])
    _text_pdf_hospital_bill("TC010", "hospital_bill", "Apollo Hospitals", "Deepak Shah",
                            "03-Nov-2024", [("Consultation Fee", 1500.0), ("Medicines", 3000.0)])

    # TC011 — component failure (alternative medicine)
    prescription("TC011", "prescription.jpg", "Vaidya T. Krishnan", "AYUR/KL/2345/2019",
                 "Kavita Nair", "28-Oct-2024", "Chronic Joint Pain", [], tests=["Panchakarma Therapy"])
    _text_pdf_prescription("TC011", "prescription", "Vaidya T. Krishnan", "AYUR/KL/2345/2019",
                           "Kavita Nair", "28-Oct-2024", "Chronic Joint Pain", [], tests=["Panchakarma Therapy"])
    hospital_bill("TC011", "hospital_bill.jpg", "Ayur Wellness Centre", "Kavita Nair",
                  "28-Oct-2024", [("Panchakarma Therapy (5 sessions)", 3000.0), ("Consultation", 1000.0)])
    _text_pdf_hospital_bill("TC011", "hospital_bill", "Ayur Wellness Centre", "Kavita Nair",
                            "28-Oct-2024", [("Panchakarma Therapy (5 sessions)", 3000.0), ("Consultation", 1000.0)])

    # TC012 — bariatric / excluded
    prescription("TC012", "prescription.jpg", "P. Banerjee", "WB/34567/2015",
                 "Anita Desai", "18-Oct-2024", "Morbid Obesity — BMI 37", [], tests=["Bariatric Consultation"])
    _text_pdf_prescription("TC012", "prescription", "P. Banerjee", "WB/34567/2015",
                           "Anita Desai", "18-Oct-2024", "Morbid Obesity — BMI 37", [], tests=["Bariatric Consultation"])
    hospital_bill("TC012", "hospital_bill.jpg", "Bariatric Care Clinic", "Anita Desai",
                  "18-Oct-2024", [("Bariatric Consultation", 3000.0), ("Personalised Diet Program", 5000.0)])
    _text_pdf_hospital_bill("TC012", "hospital_bill", "Bariatric Care Clinic", "Anita Desai",
                            "18-Oct-2024", [("Bariatric Consultation", 3000.0), ("Personalised Diet Program", 5000.0)])

    print(f"\nAll documents saved to: {OUT_DIR}/")
    print("Each document has 3 versions: .jpg  |  .pdf (scanned)  |  _text.pdf (selectable text)")


if __name__ == "__main__":
    main()
