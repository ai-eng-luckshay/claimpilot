"""Extraction agent prompt — instructs Gemini to classify and OCR each uploaded document."""

# ---------------------------------------------------------------------------
# Extraction agent (extraction.py)
# Instructs Gemini to classify and OCR each uploaded document.
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT = """\
You are processing a health insurance claim. The documents above are labeled with their index and filename.

For EACH document, in order:
1. Classify its type — choose exactly one from the types below.
2. Extract every readable field:
   patient_name, doctor_name, doctor_registration, date, diagnosis,
   medicines (list), hospital_name, line_items (list of description+amount),
   total (number), test_name — use null for missing or unreadable fields.
3. Set quality_flags — include any that apply:
   RUBBER_STAMP_OVER_TEXT, DOCUMENT_ALTERATION, MULTILINGUAL, PARTIAL_DOCUMENT
4. Set confidence (0.0–1.0) based on how clearly you could read this document.

## Document Type Definitions (classify strictly by these)

HOSPITAL_BILL — A billing or invoice document showing itemized charges and a total amount payable.
  Use this for ANY financial bill or receipt from ANY healthcare provider:
  hospitals, clinics, dental clinics, eye clinics, physiotherapy centres, diagnostic centres, etc.
  Key signals: line items with amounts, "Total", "Bill No", "Invoice", "Receipt", "Amount Due".
  ⚠ A dental clinic bill is HOSPITAL_BILL, not DENTAL_REPORT.
  ⚠ A diagnostic centre invoice is HOSPITAL_BILL, not DIAGNOSTIC_REPORT.

PRESCRIPTION — A doctor's written instruction for medicines or tests. Contains Rx, drug names,
  dosage, doctor registration number, and doctor's signature/stamp.

LAB_REPORT — Any clinical test or diagnostic result document. Use this for ALL of the following:
  blood tests, urine analysis, biopsy results, MRI reports, CT scan reports, X-ray reports,
  ultrasound reports, ECG reports, PET scan reports, and any other lab or imaging result.
  Key signal: contains test/finding results and is NOT a billing document.
  ⚠ Use LAB_REPORT for MRI, CT, and ultrasound reports — there is no DIAGNOSTIC_REPORT type.

PHARMACY_BILL — A pharmacy receipt/invoice specifically for drugs and medicines purchased.
  Key signals: drug names with quantities and prices, pharmacy licence number.

DENTAL_REPORT — A CLINICAL dental examination or treatment record (not a billing document).
  Contains dental charting, clinical findings, X-ray readings, tooth condition notes, or
  treatment notes written by the dentist. Has no itemized pricing.

DISCHARGE_SUMMARY — A hospital discharge document summarising an inpatient admission, diagnosis,
  treatment given, and follow-up instructions. Issued on patient discharge.

UNKNOWN — Use only when the document is illegible, too damaged to classify, or clearly does not
  belong to any category above.

## Cross-Document Validation (after processing all documents)

5. Patient name consistency — compare patient_name across ALL documents:
   - Set patient_name_consistent=false ONLY if two or more documents have names that clearly
     belong to DIFFERENT individuals (e.g. "Rajesh Kumar" vs "Arjun Mehta").
   - Do NOT flag acceptable variations: initials ("R. Kumar" = "Rajesh Kumar"),
     titles ("Dr. Priya" = "Priya Sharma"), minor spelling differences, or one document
     having no name at all.
   - When patient_name_consistent=false, set patient_name_mismatch_details describing
     which documents had which names.

Return your answer in the structured format: a "documents" list with one entry per document
(in the same order), plus the patient_name_consistent and patient_name_mismatch_details fields.\
"""
