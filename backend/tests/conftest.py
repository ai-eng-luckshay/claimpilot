"""Shared test fixtures."""
from typing import cast
import pytest
from backend.src.services.policy import load_policy
from backend.src.pipeline.state import ClaimState


@pytest.fixture(scope="session", autouse=True)
def policy():
    return load_policy()


def make_state(request_data: dict) -> ClaimState:
    """Build a minimal ClaimState for unit testing individual agents."""
    return cast(ClaimState, {
        "request": request_data,
        "failed_components": [],
        "trace": {},
    })
