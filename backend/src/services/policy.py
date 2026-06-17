import json
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field

from backend.src.config.logger_config import error_logger, application_logger


_POLICY_FILE = Path(__file__).parent.parent.parent / "data" / "policy_terms.json"


@dataclass
class MemberRecord:
    member_id: str
    name: str
    join_date: str
    relationship: str
    primary_member_id: str | None = None
    dependents: list[str] = field(default_factory=list)


@dataclass
class PolicyData:
    policy_id: str
    members: dict[str, MemberRecord]
    coverage: dict
    opd_categories: dict
    waiting_periods: dict
    exclusions: dict
    pre_authorization: dict
    network_hospitals: list[str]
    submission_rules: dict
    document_requirements: dict
    fraud_thresholds: dict

    def get_member(self, member_id: str) -> MemberRecord | None:
        return self.members.get(member_id)

    def get_category_config(self, category: str) -> dict | None:
        return self.opd_categories.get(category.lower())

    def get_document_requirements(self, category: str) -> dict:
        return self.document_requirements.get(category.upper(), {"required": [], "optional": []})

    def is_network_hospital(self, hospital_name: str | None) -> bool:
        if not hospital_name:
            return False
        hospital_lower = hospital_name.lower()
        return any(
            h.lower() in hospital_lower or hospital_lower in h.lower()
            for h in self.network_hospitals
        )


def get_policy_context(member_id: str, claim_category: str) -> dict:
    """Return a filtered policy context for Gemini — excludes network hospitals, document requirements, fraud thresholds."""
    policy = load_policy()
    member = policy.get_member(member_id)
    category_config = policy.opd_categories.get(claim_category.lower())
    return {
        "member": {
            "member_id": member.member_id,
            "name": member.name,
            "join_date": member.join_date,
            "relationship": member.relationship,
        } if member else None,
        "coverage": policy.coverage,
        "claim_category": claim_category.upper(),
        "claim_category_config": category_config,
        "waiting_periods": policy.waiting_periods,
        "exclusions": policy.exclusions,
        "pre_authorization": policy.pre_authorization,
        "network_hospitals": policy.network_hospitals,
        "fraud_thresholds": policy.fraud_thresholds,
    }


@lru_cache(maxsize=1)
def load_policy() -> PolicyData:
    application_logger.info("load_policy: loading from %s", _POLICY_FILE)
    try:
        with open(_POLICY_FILE) as f:
            raw = json.load(f)
    except Exception as e:
        error_logger.error("load_policy: failed to read policy file — %s", e)
        raise

    members = {
        m["member_id"]: MemberRecord(
            member_id=m["member_id"],
            name=m["name"],
            join_date=m.get("join_date", "2024-04-01"),
            relationship=m["relationship"],
            primary_member_id=m.get("primary_member_id"),
            dependents=m.get("dependents", []),
        )
        for m in raw["members"]
    }

    policy = PolicyData(
        policy_id=raw["policy_id"],
        members=members,
        coverage=raw["coverage"],
        opd_categories=raw["opd_categories"],
        waiting_periods=raw["waiting_periods"],
        exclusions=raw["exclusions"],
        pre_authorization=raw["pre_authorization"],
        network_hospitals=raw["network_hospitals"],
        submission_rules=raw["submission_rules"],
        document_requirements=raw["document_requirements"],
        fraud_thresholds=raw["fraud_thresholds"],
    )
    application_logger.info(
        "load_policy: loaded policy_id=%s members=%d", policy.policy_id, len(policy.members)
    )
    return policy
