import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Numeric, Float, Date, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member_id = Column(String, nullable=False, index=True)
    policy_id = Column(String, nullable=False)
    claim_category = Column(String, nullable=False)
    treatment_date = Column(Date, nullable=False)
    claimed_amount = Column(Numeric(10, 2), nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    decision = Column(String)
    approved_amount = Column(Numeric(10, 2))
    confidence_score = Column(Float)
    rejection_reasons = Column(JSONB, default=list)
    decision_reason = Column(Text)

    trace = Column(JSONB, default=dict)
    failed_components = Column(JSONB, default=list)
    source_channel = Column(String, default="WEB")

    documents = relationship("ClaimDocument", back_populates="claim", cascade="all, delete-orphan")


class ClaimDocument(Base):
    __tablename__ = "claim_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=False, index=True)
    file_name = Column(String, nullable=False)
    document_type = Column(String)
    file_path = Column(String)       # relative path under uploads/; None for test-mode docs
    extraction = Column(JSONB, default=dict)
    quality_flags = Column(JSONB, default=list)
    confidence = Column(Float)

    claim = relationship("Claim", back_populates="documents")
