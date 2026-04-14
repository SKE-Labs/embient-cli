"""Unit tests for Basement API loaders.

Tests BasementSkillsLoader metadata loading, agent filtering, and caching.
Store-write functionality was removed — agents read skill content via
SupabaseStorageBackend now.
"""

from unittest.mock import AsyncMock, patch

import pytest
from deepanalysts.backends.basement import BasementSkillsLoader


@pytest.mark.anyio
async def test_basement_skills_loader_returns_metadata():
    """Test BasementSkillsLoader returns SkillMetadata for system prompt injection."""
    mock_skills = [
        {
            "name": "test-skill",
            "path": "/skills/test-skill",
            "content": "# Test Skill\nThis is a test.",
            "description": "A test skill",
            "target_agents": ["technical_analyst"],
            "assets": [],
            "metadata": {},
        }
    ]

    jwt_token = "test-jwt"
    loader = BasementSkillsLoader(token_provider=lambda: jwt_token)

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        skills = await loader.load_skills(agent_name="technical_analyst", user_id="user-123")

        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill"
        assert skills[0]["path"] == "/skills/test-skill/SKILL.md"
        assert skills[0]["description"] == "A test skill"


@pytest.mark.anyio
async def test_basement_skills_loader_filters_by_agent():
    """Test BasementSkillsLoader filters skills by target_agents."""
    mock_skills = [
        {
            "name": "shared-skill",
            "path": "/skills/shared-skill",
            "content": "# Shared Skill",
            "description": "Shared",
            "target_agents": [],  # Empty = all agents
            "assets": [],
            "metadata": {},
        },
        {
            "name": "ta-only-skill",
            "path": "/skills/ta-only-skill",
            "content": "# TA Only",
            "description": "TA only",
            "target_agents": ["technical_analyst"],
            "assets": [],
            "metadata": {},
        },
        {
            "name": "other-skill",
            "path": "/skills/other-skill",
            "content": "# Other",
            "description": "Other",
            "target_agents": ["fundamental_analyst"],
            "assets": [],
            "metadata": {},
        },
    ]

    jwt_token = "jwt"
    loader = BasementSkillsLoader(token_provider=lambda: jwt_token)

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        skills = await loader.load_skills(agent_name="technical_analyst", user_id="user-123")

        skill_names = [s["name"] for s in skills]
        assert "shared-skill" in skill_names
        assert "ta-only-skill" in skill_names
        assert "other-skill" not in skill_names


@pytest.mark.anyio
async def test_basement_skills_loader_wildcard_target():
    """Test BasementSkillsLoader handles wildcard target_agents."""
    mock_skills = [
        {
            "name": "wildcard-skill",
            "path": "/skills/wildcard-skill",
            "content": "# Wildcard Skill",
            "description": "Wildcard",
            "target_agents": ["*"],
            "assets": [],
            "metadata": {},
        },
    ]

    jwt_token = "jwt"
    loader = BasementSkillsLoader(token_provider=lambda: jwt_token)

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        skills = await loader.load_skills(agent_name="any_agent", user_id="test-user-123")

        assert len(skills) == 1
        assert skills[0]["name"] == "wildcard-skill"


@pytest.mark.anyio
async def test_basement_skills_loader_no_token():
    """Test BasementSkillsLoader returns empty list when no token."""
    loader = BasementSkillsLoader(token_provider=lambda: None)

    skills = await loader.load_skills(agent_name="technical_analyst")

    assert skills == []


@pytest.mark.anyio
async def test_basement_skills_loader_caching():
    """Test BasementSkillsLoader caches API responses."""
    mock_skills = [
        {
            "name": "cached-skill",
            "path": "/skills/cached-skill",
            "content": "# Cached",
            "description": "Cached",
            "target_agents": [],
            "assets": [],
            "metadata": {},
        }
    ]

    jwt_token = "jwt"
    loader = BasementSkillsLoader(token_provider=lambda: jwt_token)

    with patch(
        "deepanalysts.backends.basement.basement_client.get_active_skills",
        new_callable=AsyncMock,
    ) as mock_get_skills:
        mock_get_skills.return_value = mock_skills

        # First call should hit API
        await loader.load_skills(agent_name="ta", user_id="user1")
        assert mock_get_skills.call_count == 1

        # Second call should use cache
        await loader.load_skills(agent_name="fa", user_id="user1")
        assert mock_get_skills.call_count == 1

        # Clear cache and call again
        loader.clear_cache()
        await loader.load_skills(agent_name="ta", user_id="user1")
        assert mock_get_skills.call_count == 2
