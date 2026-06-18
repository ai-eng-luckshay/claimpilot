"""Dead letter queue — non-functional stub.

Signals intent: claims that could not be saved to the DB after all retries
should be published here so they can be replayed once the DB recovers.

Production implementation: swap NoOpDLQ for SQSDeadLetterQueue or RedisStreamDLQ.
"""

from abc import ABC, abstractmethod

from backend.src.config.logger_config import error_logger
from backend.src.pipeline.state import ClaimState


class DeadLetterQueue(ABC):
    @abstractmethod
    def publish(self, claim_id: str, state: ClaimState, error: str) -> None:
        """Publish a failed claim so it can be replayed once the DB recovers."""
        ...


class NoOpDLQ(DeadLetterQueue):
    """Stub — logs the intent but does not persist anywhere."""

    def publish(self, claim_id: str, state: ClaimState, error: str) -> None:
        error_logger.error(
            "DLQ(stub): claim_id=%s would be published — error=%s", claim_id, error
        )


def get_dlq() -> DeadLetterQueue:
    return NoOpDLQ()
