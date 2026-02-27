from src.agents.common.memory.filters import is_profile_identity_memory


def test_is_profile_identity_memory_matches_profile_facts() -> None:
    assert is_profile_identity_memory("Name is Song Teng")
    assert is_profile_identity_memory("display name is Song")
    assert is_profile_identity_memory("Email is song@xyz.com")


def test_is_profile_identity_memory_ignores_non_profile_memories() -> None:
    assert not is_profile_identity_memory("Likes coffee")
    assert not is_profile_identity_memory("Asked HR to confirm annual vacation days entitlement")
    assert not is_profile_identity_memory("")
