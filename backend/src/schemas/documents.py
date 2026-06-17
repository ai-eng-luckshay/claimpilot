from pydantic import BaseModel


class LineItem(BaseModel):
    description: str
    amount: float


class PrescriptionContent(BaseModel):
    doctor_name: str | None = None
    doctor_registration: str | None = None
    patient_name: str | None = None
    date: str | None = None
    diagnosis: str | None = None
    medicines: list[str] | None = None
    tests_ordered: list[str] | None = None
    treatment: str | None = None


class HospitalBillContent(BaseModel):
    hospital_name: str | None = None
    patient_name: str | None = None
    date: str | None = None
    line_items: list[LineItem] | None = None
    total: float | None = None


class LabReportContent(BaseModel):
    patient_name: str | None = None
    test_name: str | None = None
    date: str | None = None
    results: dict | None = None


class PharmacyBillContent(BaseModel):
    patient_name: str | None = None
    date: str | None = None
    items: list[dict] | None = None
    total: float | None = None


class DentalReportContent(BaseModel):
    patient_name: str | None = None
    date: str | None = None
    procedures: list[str] | None = None
    notes: str | None = None


class ExtractedDocument(BaseModel):
    classified_type: str          # Gemini-classified type — what the document actually is
    file_name: str
    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    date: str | None = None
    diagnosis: str | None = None
    medicines: list[str] | None = None
    hospital_name: str | None = None
    line_items: list[LineItem] | None = None
    total: float | None = None
    test_name: str | None = None
    quality_flags: list[str] = []
    overall_confidence: float = 1.0
