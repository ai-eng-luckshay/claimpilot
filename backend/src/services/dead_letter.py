"""Dead letter queue — captures claims that could not be saved to the database.

Current implementation: local file fallback (writes JSON to uploads/dlq/).
Production implementation: swap LocalFileDLQ for SQSDealLetterQueue or RedisStreamDLQ.
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState


class DeadLetterQueue(ABC):
    """Abstract dead letter queue. Implement publish() for each backend."""

    @abstractmethod
    def publish(self, claim_id: str, state: ClaimState, error: str) -> None:
        """Publish a failed claim so it can be replayed once the DB recovers."""
        ...


class LocalFileDLQ(DeadLetterQueue):
    """
    Writes failed claims as JSON files under uploads/dlq/.
    Suitable for single-instance deployments. Not suitable for multi-instance.

    TODO: Replace with SQSDealLetterQueue or RedisStreamDLQ for production.
    """

    def __init__(self, dlq_dir: Path | None = None) -> None:
        self._dlq_dir = dlq_dir or (
            Path(__file__).parent.parent.parent.parent / "uploads" / "dlq"
        )

    def publish(self, claim_id: str, state: ClaimState, error: str) -> None:
        try:
            self._dlq_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "claim_id": claim_id,
                "error": error,
                "decision": state.get("decision"),
                "member_id": state.get("request", {}).get("member_id"),
                "failed_components": list(state.get("failed_components", [])),
            }
            (self._dlq_dir / f"{claim_id}.json").write_text(json.dumps(payload, indent=2))
            error_logger.warning(
                "DeadLetterQueue: wrote claim_id=%s to %s", claim_id, self._dlq_dir
            )
        except Exception as e:
            error_logger.error(
                "DeadLetterQueue: failed to write claim_id=%s — %s", claim_id, e
            )


# ---------------------------------------------------------------------------
# TODO: production backends (not yet implemented)
# ---------------------------------------------------------------------------
# class SQSDeadLetterQueue(DeadLetterQueue):
#     def publish(self, claim_id, state, error):
#         import boto3
#         boto3.client("sqs").send_message(
#             QueueUrl=os.environ["DLQ_URL"],
#             MessageBody=json.dumps({"claim_id": claim_id, "error": error, ...}),
#         )
#
# class RedisStreamDLQ(DeadLetterQueue):
#     def publish(self, claim_id, state, error):
#         import redis
#         redis.Redis().xadd("claims:dlq", {"claim_id": claim_id, "error": error})


def get_dlq() -> DeadLetterQueue:
    """Factory — returns the configured dead letter queue implementation."""
    return LocalFileDLQ()
