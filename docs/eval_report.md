# Evaluation Report

> Generated: 2026-06-18 08:57 UTC  
> API: `https://claimpilot-api-pg29.onrender.com`  
> Document format: `text_pdfs` (TC002 always runs as `images`)  
> Result: **12/12 passed**

---

## Summary

| Case | Name | Expected | Actual | Amount | Confidence | Result |
|---|---|---|---|---|---|---|
| TC001 | Wrong Document Uploaded | `early stop` | `DOCUMENT_VALIDATION_FAILED` | — | — | ✅ PASS |
| TC002 | Unreadable Document | `early stop` | `DOCUMENT_UNREADABLE` | — | — | ✅ PASS |
| TC003 | Documents Belong to Different Patients | `early stop` | `REJECTED` | — | 1.00 | ✅ PASS |
| TC004 | Clean Consultation - Full Approval | `APPROVED` | `APPROVED` | ₹1,350.00 | 0.90 | ✅ PASS |
| TC005 | Waiting Period - Diabetes | `REJECTED` | `REJECTED` | ₹0.00 | 0.75 | ✅ PASS |
| TC006 | Dental Partial Approval - Cosmetic Exclusion | `PARTIAL` | `PARTIAL` | ₹8,000.00 | 0.90 | ✅ PASS |
| TC007 | MRI Without Pre-Authorization | `REJECTED` | `REJECTED` | — | 0.75 | ✅ PASS |
| TC008 | Per-Claim Limit Exceeded | `REJECTED` | `REJECTED` | — | 0.90 | ✅ PASS |
| TC009 | Fraud Signal - Multiple Same-Day Claims | `MANUAL_REVIEW` | `MANUAL_REVIEW` | — | 0.60 | ✅ PASS |
| TC010 | Network Hospital - Discount Applied | `APPROVED` | `APPROVED` | ₹3,240.00 | 0.90 | ✅ PASS |
| TC011 | Component Failure - Graceful Degradation | `APPROVED` | `APPROVED` | ₹4,000.00 | 0.60 | ✅ PASS |
| TC012 | Excluded Treatment | `REJECTED` | `REJECTED` | ₹0.00 | 0.90 | ✅ PASS |

**12 passed, 0 failed** out of 12 test cases.

---

## Detailed Results

### TC001 — Wrong Document Uploaded  ✅ PASS

**Description:** Member submits two prescriptions for a consultation claim that requires a prescription and a hospital bill.

**Expected:**
- No decision (system must stop before adjudication)
- _Stop before making any claim decision_
- _Tell the member specifically what document type was uploaded and what is needed instead_
- _Not return a generic error — the message must name the uploaded document type and the required document type_

**Actual output:**
- Error type: `DOCUMENT_VALIDATION_FAILED`
- Message: _You uploaded: PRESCRIPTION, PRESCRIPTION. A CONSULTATION claim requires: PRESCRIPTION, HOSPITAL_BILL. Missing: HOSPITAL_BILL. Please upload the missing document and resubmit._
- Uploaded: `PRESCRIPTION`, `PRESCRIPTION`
- Required: `PRESCRIPTION`, `HOSPITAL_BILL`

**Pipeline trace:**

_No trace available_

_Response time: 3.4s_

---

### TC002 — Unreadable Document  ✅ PASS

**Description:** Member uploads a valid prescription but a blurry, unreadable photo of their pharmacy bill.

**Expected:**
- No decision (system must stop before adjudication)
- _Identify that the pharmacy bill cannot be read_
- _Ask the member to re-upload that specific document_
- _Not reject the claim outright_

**Actual output:**
- Error type: `DOCUMENT_UNREADABLE`
- Message: _The document you uploaded (blurry_bill.jpg) is too blurry to read. Please take a clearer photo and re-upload that document._
- Unreadable file: `blurry_bill.jpg`

**Pipeline trace:**

_No trace available_

_Response time: 0.8s_

---

### TC003 — Documents Belong to Different Patients  ✅ PASS

**Description:** The prescription is for Rajesh Kumar but the hospital bill is for a different patient, Arjun Mehta.

**Expected:**
- No decision (system must stop before adjudication)
- _Detect that the documents belong to different people_
- _Surface this to the member with the specific names found on each document_
- _Not proceed to a claim decision_

**Actual output:**
- Decision: `REJECTED`
- Approved amount: —
- Confidence score: 1.00
- Reason: _Patient name mismatch detected: Document 1 (prescription_rajesh_text.pdf) has patient name 'Rajesh Kumar', while Document 2 (bill_arjun_text.pdf) has patient name 'Arjun Mehta'._
- Rejection reasons: `PATIENT_NAME_MISMATCH`
- Claim ID: `632fde68-1710-4e61-a026-d98c909e9d4b`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_rajesh_text.pdf` → `SKIP` (pdf)
  - `bill_arjun_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_rajesh_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `bill_arjun_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
  - ⚠ patient name inconsistency detected
- **patient_name_check**: `FAIL` — Document 1 (prescription_rajesh_text.pdf) has patient name 'Rajesh Kumar', while Document 2 (bill_arjun_text.pdf) has patient name 'Arjun Mehta'.
- **save_to_db**: ✓ persisted (`632fde68-1710-4e61-a026-d98c909e9d4b`)

_Response time: 3.5s_

---

### TC004 — Clean Consultation - Full Approval  ✅ PASS

**Description:** Complete, valid consultation claim with correct documents, valid member, covered treatment, within all limits.

**Expected:**
- Decision: `APPROVED`
- Approved amount: ₹1,350
- Notes: 10% co-pay applied on consultation category (₹150 deducted)

**Actual output:**
- Decision: `APPROVED`
- Approved amount: ₹1,350.00
- Confidence score: 0.90
- Reason: _The claim is for a consultation and diagnostic tests related to Viral Fever. The member joined on 2024-04-01, and the treatment date of 2024-11-01 is well past the initial 30-day waiting period. The claim amount of ₹1,500 is within the per-claim limit of ₹5,000 and the annual OPD limit. As the hospital is not in the network, no discount is applied. A 10% copay is deducted as per policy._
- Claim ID: `cfafa399-37ac-43b7-8bc5-5999c46e0ddd`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: `APPROVED` at confidence=0.9
  - calculation: co-pay 10.0% = ₹150.00 → final ₹1,350.00
- **save_to_db**: ✓ persisted (`cfafa399-37ac-43b7-8bc5-5999c46e0ddd`)

_Response time: 5.1s_

---

### TC005 — Waiting Period - Diabetes  ✅ PASS

**Description:** Member joined 2024-09-01. Claims for diabetes treatment on 2024-10-15, which is within the 90-day waiting period for diabetes.

**Expected:**
- Decision: `REJECTED`
- _State the date from which the member will be eligible for diabetes-related claims_

**Actual output:**
- Decision: `REJECTED`
- Approved amount: ₹0.00
- Confidence score: 0.75
- Reason: _The member joined on 2024-09-01. The diagnosis is Type 2 Diabetes Mellitus, which has a specific condition waiting period of 90 days. The treatment date of 2024-10-15 is within this waiting period (which ends on 2024-11-30)._
- Rejection reasons: `WAITING_PERIOD`
- Claim ID: `a5e005ee-6f4c-460f-837c-77759cc1cac8`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: `REJECTED` at confidence=0.75
  - rejection reasons: `WAITING_PERIOD`
  - eligibility date: 2024-11-30
  - calculation: network discount 20.0% = ₹600.00 → co-pay 10.0% = ₹240.00 → final ₹0.00
- **save_to_db**: ✓ persisted (`a5e005ee-6f4c-460f-837c-77759cc1cac8`)

_Response time: 5.5s_

---

### TC006 — Dental Partial Approval - Cosmetic Exclusion  ✅ PASS

**Description:** Bill includes root canal treatment (covered) and teeth whitening (cosmetic, excluded). System must approve only the covered procedure.

**Expected:**
- Decision: `PARTIAL`
- Approved amount: ₹8,000
- _Itemize which line items were approved and which were rejected_
- _State the reason for each rejection at the line-item level_

**Actual output:**
- Decision: `PARTIAL`
- Approved amount: ₹8,000.00
- Confidence score: 0.90
- Reason: _The claim includes both covered procedures (Root Canal Treatment) and excluded procedures (Teeth Whitening). The covered portion is approved, while the cosmetic procedure is rejected based on policy exclusions._
- Claim ID: `cf3e8149-caef-4800-b737-9702954f5778`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 1 doc(s)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: HOSPITAL_BILL
  - classified: HOSPITAL_BILL
- **adjudicate**: `PARTIAL` at confidence=0.9
  - dental approved: Root Canal Treatment (₹8,000.00)
  - dental rejected: Teeth Whitening (₹4,000.00)
- **save_to_db**: ✓ persisted (`cf3e8149-caef-4800-b737-9702954f5778`)

_Response time: 7.3s_

---

### TC007 — MRI Without Pre-Authorization  ✅ PASS

**Description:** MRI scan costing ₹15,000 submitted without pre-authorization. Policy requires pre-auth for MRI above ₹10,000.

**Expected:**
- Decision: `REJECTED`
- _Explain that pre-authorization was required and not obtained_
- _Tell the member what they should do to resubmit with pre-auth_

**Actual output:**
- Decision: `REJECTED`
- Approved amount: —
- Confidence score: 0.75
- Reason: _The claim is rejected because it involves an MRI scan exceeding the ₹10,000 pre-authorization threshold without a valid pre-authorization document. The diagnosis of 'Lumbar Disc Herniation' does not trigger the 'hernia' waiting period due to strict word-boundary matching rules._
- Rejection reasons: `PRE_AUTH_MISSING`
- Claim ID: `9e110cb8-f3eb-43ff-8581-790c78284d04`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `lab_report_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 3 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `lab_report_text.pdf` → `LAB_REPORT` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL
  - classified: PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL
- **adjudicate**: `REJECTED` at confidence=0.75
  - rejection reasons: `PRE_AUTH_MISSING`
- **save_to_db**: ✓ persisted (`9e110cb8-f3eb-43ff-8581-790c78284d04`)

_Response time: 5.6s_

---

### TC008 — Per-Claim Limit Exceeded  ✅ PASS

**Description:** Claimed amount of ₹7,500 exceeds the per-claim limit of ₹5,000.

**Expected:**
- Decision: `REJECTED`
- _State the per-claim limit and the claimed amount clearly in the rejection message_

**Actual output:**
- Decision: `REJECTED`
- Approved amount: —
- Confidence score: 0.90
- Reason: _The claim is rejected because the total claimed amount of ₹7,500.00 exceeds the per-claim limit of ₹5,000.00 defined in the policy context._
- Rejection reasons: `PER_CLAIM_EXCEEDED`
- Claim ID: `3bef4fd5-2fea-4bd8-ab16-503330c10bc4`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: `REJECTED` at confidence=0.9
  - rejection reasons: `PER_CLAIM_EXCEEDED`
  - calculation: co-pay 10.0% = ₹750.00 → final ₹0.00
- **save_to_db**: ✓ persisted (`3bef4fd5-2fea-4bd8-ab16-503330c10bc4`)

_Response time: 4.8s_

---

### TC009 — Fraud Signal - Multiple Same-Day Claims  ✅ PASS

**Description:** Member EMP008 has already submitted 3 claims today before this one arrives. This is the 4th claim from the same member on the same day.

**Expected:**
- Decision: `MANUAL_REVIEW`
- _Flag the unusual same-day claim pattern_
- _Route to manual review rather than auto-rejecting_
- _Include the specific signals that triggered the flag in the output_

**Actual output:**
- Decision: `MANUAL_REVIEW`
- Approved amount: —
- Confidence score: 0.60
- Reason: _The claim has been flagged for manual review due to a potential fraud pattern. The member has submitted 4 claims for the same treatment date (2024-10-30), which exceeds the fraud threshold of 2 same-day claims._
- Claim ID: `93cc008d-aab1-49db-9881-e3ef7da68105`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: `MANUAL_REVIEW` at confidence=0.6
  - calculation: co-pay 10.0% = ₹480.00 → final ₹0.00
- **save_to_db**: ✓ persisted (`93cc008d-aab1-49db-9881-e3ef7da68105`)

_Response time: 5.0s_

---

### TC010 — Network Hospital - Discount Applied  ✅ PASS

**Description:** Valid claim at Apollo Hospitals, a network hospital. Network discount must be applied before co-pay.

**Expected:**
- Decision: `APPROVED`
- Approved amount: ₹3,240
- Notes: Network discount (20%) applied first on ₹4,500 = ₹3,600. Co-pay (10%) applied on ₹3,600 = ₹360 deducted. Final: ₹3,240.
- _Apply network discount before co-pay, not after_
- _Show the breakdown of discount and co-pay in the decision output_

**Actual output:**
- Decision: `APPROVED`
- Approved amount: ₹3,240.00
- Confidence score: 0.90
- Reason: _The claim is for a consultation at a network hospital. The member has completed the initial waiting period. The claim amount is within the per-claim limit and the annual OPD limit. A 20% network discount and 10% copay have been applied._
- Claim ID: `f5b7ffaf-ac7d-40da-b1ac-549afc7d742d`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: `APPROVED` at confidence=0.9
  - calculation: network discount 20.0% = ₹900.00 → co-pay 10.0% = ₹360.00 → final ₹3,240.00
- **save_to_db**: ✓ persisted (`f5b7ffaf-ac7d-40da-b1ac-549afc7d742d`)

_Response time: 7.0s_

---

### TC011 — Component Failure - Graceful Degradation  ✅ PASS

**Description:** One component of your system fails mid-processing (simulate with the flag below). The overall pipeline must continue, produce a decision, and make the failure visible in the output with an appropriately reduced confidence score.

**Expected:**
- Decision: `APPROVED`
- _Not crash or return a 500 error_
- _Indicate in the output that a component failed and was skipped_
- _Return a confidence score lower than a normal full-pipeline approval_
- _Include a note that manual review is recommended due to incomplete processing_

**Actual output:**
- Decision: `APPROVED`
- Approved amount: ₹4,000.00
- Confidence score: 0.60
- Reason: _Policy check skipped due to a component failure — manual review recommended._
- Failed components: `policy_check`
- Claim ID: `91ae5921-1040-4665-8488-435e3f2f0a89`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: skipped — simulate_component_failure
- **save_to_db**: ✓ persisted (`91ae5921-1040-4665-8488-435e3f2f0a89`)

_Response time: 3.8s_

---

### TC012 — Excluded Treatment  ✅ PASS

**Description:** Member claims for bariatric consultation and a diet program. Obesity treatment is explicitly excluded under the policy.

**Expected:**
- Decision: `REJECTED`

**Actual output:**
- Decision: `REJECTED`
- Approved amount: ₹0.00
- Confidence score: 0.90
- Reason: _The claim is rejected because the diagnosis 'Morbid Obesity' and the services 'Bariatric Consultation' and 'Personalised Diet Program' fall under the policy exclusion for 'Obesity and weight loss programs'._
- Rejection reasons: `EXCLUDED_CONDITION`
- Claim ID: `c733fef1-13b6-4e4f-a840-62c9ac01d1c3`

**Pipeline trace:**

- **blur_gate**: `PASS`
  - `prescription_text.pdf` → `SKIP` (pdf)
  - `hospital_bill_text.pdf` → `SKIP` (pdf)
- **extraction**: ok, 2 doc(s)
  - `prescription_text.pdf` → `PRESCRIPTION` (confidence=1.0)
  - `hospital_bill_text.pdf` → `HOSPITAL_BILL` (confidence=1.0)
- **document_validation**: `PASS`
  - required: PRESCRIPTION, HOSPITAL_BILL
  - classified: PRESCRIPTION, HOSPITAL_BILL
- **adjudicate**: `REJECTED` at confidence=0.9
  - rejection reasons: `EXCLUDED_CONDITION`
  - calculation: co-pay 10.0% = ₹0.00 → final ₹0.00
- **save_to_db**: ✓ persisted (`c733fef1-13b6-4e4f-a840-62c9ac01d1c3`)

_Response time: 4.9s_

---
