"""Basement API loaders for skills and memory.

Provides loader classes that fetch skills and memories from the Basement API
instead of file-based backends. These loaders can be passed to the
MemoryMiddleware and SkillsMiddleware for API-based loading.

Note: These loaders require a token provider to be configured. The token
provider can be a static token, a callable, or a context variable getter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from deepanalysts.clients.basement import BasementClient, basement_client
from deepanalysts.middleware.skills import SkillMetadata

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenProvider(Protocol):
    """Protocol for getting JWT tokens."""

    def __call__(self) -> str | None:
        """Get the current JWT token."""
        ...


class BasementMemoryLoader:
    """Loads user memories from Basement API.

    Fetches active memories via GET /api/v1/memories/active and returns them
    in the format expected by MemoryMiddleware.

    Example:
        ```python
        # With token provider function
        loader = BasementMemoryLoader(token_provider=get_jwt_from_context)
        middleware = MemoryMiddleware(loader=loader)

        # With client that has token configured
        client = BasementClient(token="jwt-token")
        loader = BasementMemoryLoader(client=client)
        ```
    """

    def __init__(
        self,
        *,
        client: BasementClient | None = None,
        token_provider: Callable[[], str | None] | None = None,
    ) -> None:
        """Initialize the memory loader.

        Args:
            client: BasementClient instance to use. Defaults to global basement_client.
            token_provider: Callable that returns JWT token. Used when calling API.
        """
        self._client = client or basement_client
        self._token_provider = token_provider
        self._cache: dict[str, dict[str, str]] = {}

    def _get_token(self) -> str | None:
        """Get JWT token from provider."""
        if self._token_provider:
            return self._token_provider()
        return None

    async def load_memories(self) -> dict[str, str]:
        """Load active memories for user.

        Returns:
            Dict mapping memory name to content, compatible with MemoryMiddleware.
        """
        jwt_token = self._get_token()
        if not jwt_token:
            logger.warning("No JWT token available, skipping memory loading")
            return {}

        # Check cache (keyed by JWT to support multiple users)
        if jwt_token in self._cache:
            return self._cache[jwt_token]

        memories = await self._client.get_active_memories(jwt_token)

        # Convert to dict format expected by MemoryMiddleware
        contents: dict[str, str] = {}
        for mem in memories:
            name = mem.get("name", "")
            content = mem.get("content", "")
            if name and content:
                contents[name] = content

        self._cache[jwt_token] = contents
        logger.debug(f"Loaded {len(contents)} memories from Basement API")
        return contents

    def clear_cache(self) -> None:
        """Clear the memory cache."""
        self._cache.clear()


class BasementSkillsLoader:
    """Loads user skills from Basement API with agent filtering.

    Fetches active skills via GET /api/v1/skills/active and filters them
    based on target_agents to ensure each subagent only sees relevant skills.
    Returns SkillMetadata for system prompt injection via SkillsMiddleware.

    Agents read skill *content* via ``read_file("/skills/...")`` through
    SupabaseStorageBackend — this loader only provides metadata.

    Filtering logic:
    - Empty target_agents = load for all agents
    - "*" in target_agents = load for all agents
    - Otherwise, agent_name must be in target_agents

    Example:
        ```python
        loader = BasementSkillsLoader(token_provider=get_jwt_from_context)

        # For orchestrator (all skills without specific targeting)
        orchestrator_skills = await loader.load_skills(agent_name="orchestrator")

        # For technical analyst (only skills targeting technical_analyst)
        ta_skills = await loader.load_skills(agent_name="technical_analyst")
        ```
    """

    def __init__(
        self,
        *,
        client: BasementClient | None = None,
        token_provider: Callable[[], str | None] | None = None,
        built_in_dirs: list[str] | None = None,
    ) -> None:
        """Initialize the skills loader.

        Args:
            client: BasementClient instance to use. Defaults to global basement_client.
            token_provider: Callable that returns JWT token.
            built_in_dirs: Directories containing built-in skills (SKILL.md files).
                          These are loaded from the filesystem and merged with API skills.
        """
        self._client = client or basement_client
        self._token_provider = token_provider
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._built_in_dirs = built_in_dirs or []
        self._built_in_cache: list[dict[str, Any]] | None = None

    def _get_token(self) -> str | None:
        """Get JWT token from provider."""
        if self._token_provider:
            return self._token_provider()
        return None

    def _load_built_in_skills(self) -> list[dict[str, Any]]:
        """Load built-in skills from filesystem directories.

        Scans each built-in directory for subdirectories containing SKILL.md,
        parses YAML frontmatter, and returns skill dicts in the same format
        as the Basement API response.

        Returns:
            List of skill dicts with name, description, content, path fields.
        """
        if self._built_in_cache is not None:
            return self._built_in_cache

        skills: list[dict[str, Any]] = []
        frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

        for built_in_dir in self._built_in_dirs:
            dir_path = Path(built_in_dir)
            if not dir_path.is_dir():
                logger.warning(f"Built-in skills directory not found: {built_in_dir}")
                continue

            for skill_dir in sorted(dir_path.iterdir()):
                if not skill_dir.is_dir():
                    continue

                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                try:
                    content = skill_md.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Error reading {skill_md}: {e}")
                    continue

                # Parse YAML frontmatter
                match = frontmatter_pattern.match(content)
                if not match:
                    logger.warning(f"No valid frontmatter in {skill_md}")
                    continue

                import yaml

                try:
                    frontmatter = yaml.safe_load(match.group(1))
                except yaml.YAMLError as e:
                    logger.warning(f"Invalid YAML in {skill_md}: {e}")
                    continue

                if not isinstance(frontmatter, dict):
                    continue

                name = frontmatter.get("name", "")
                description = frontmatter.get("description", "")
                if not name or not description:
                    continue

                skills.append(
                    {
                        "name": name,
                        "description": description,
                        "content": content,
                        "path": f"/skills/{name}",
                        "target_agents": [],  # Built-in skills available to all agents
                        "metadata": frontmatter.get("metadata", {}),
                        "assets": [],
                    }
                )

        self._built_in_cache = skills
        logger.debug(f"Loaded {len(skills)} built-in skills from filesystem")
        return skills

    async def load_skills(
        self,
        agent_name: str = "orchestrator",
        user_id: str | None = None,
    ) -> list[SkillMetadata]:
        """Load skills filtered for specific agent.

        Fetches skill metadata from Basement API for system prompt injection.
        Agents read skill *content* via ``read_file("/skills/...")`` through
        the SupabaseStorageBackend — no store caching needed here.

        Args:
            agent_name: Agent to filter skills for (e.g., 'technical_analyst').
            user_id: User ID (kept for API compatibility, not used for storage).

        Returns:
            List of SkillMetadata dicts filtered by target_agents.
        """
        jwt_token = self._get_token()
        if not jwt_token:
            logger.warning("No JWT token available, skipping skill loading")
            return []

        # Load from cache or API
        if jwt_token not in self._cache:
            skills = await self._client.get_active_skills(jwt_token)
            self._cache[jwt_token] = skills
            logger.debug(f"Loaded {len(skills)} skills from Basement API")
        else:
            skills = self._cache[jwt_token]
            logger.debug("Using cached skills from Basement API")

        # Merge built-in skills with API skills (API takes precedence)
        built_in = self._load_built_in_skills()
        api_names = {s.get("name") for s in skills}
        all_skills = list(skills)
        for bi_skill in built_in:
            if bi_skill["name"] not in api_names:
                all_skills.append(bi_skill)

        # Filter by target_agents and convert to SkillMetadata
        filtered: list[SkillMetadata] = []
        for skill in all_skills:
            if self._skill_matches_agent(skill, agent_name):
                filtered.append(self._to_skill_metadata(skill))

        logger.debug(f"Filtered {len(filtered)}/{len(all_skills)} skills for agent '{agent_name}'")
        return filtered

    def _skill_matches_agent(self, skill: dict[str, Any], agent_name: str) -> bool:
        """Check if skill should be loaded for given agent.

        Args:
            skill: Skill dict from API.
            agent_name: Agent name to check against.

        Returns:
            True if skill should be loaded for this agent.
        """
        target_agents = skill.get("target_agents", [])

        # Empty target_agents = load for all agents
        if not target_agents:
            return True

        # Wildcard = load for all agents
        if "*" in target_agents:
            return True

        # Check if agent is in target list
        return agent_name in target_agents

    def _to_skill_metadata(self, skill: dict[str, Any]) -> SkillMetadata:
        """Convert API skill dict to SkillMetadata format.

        Args:
            skill: Skill dict from Basement API.

        Returns:
            SkillMetadata TypedDict compatible with SkillsMiddleware.
        """
        # Extract allowed_tools from metadata if present
        metadata = skill.get("metadata", {}) or {}
        allowed_tools = metadata.get("allowed_tools", [])
        if isinstance(allowed_tools, str):
            allowed_tools = allowed_tools.split(" ") if allowed_tools else []

        # API returns path as skill directory (e.g., "/skills/cup-and-handle").
        # SkillMetadata.path should point to SKILL.md for consistency with
        # file-based loading, so _format_skills_list can derive the directory.
        skill_path = skill.get("path", "")
        if skill_path and not skill_path.endswith("/SKILL.md"):
            skill_path = skill_path.rstrip("/") + "/SKILL.md"

        return SkillMetadata(
            name=skill.get("name", ""),
            description=skill.get("description", ""),
            path=skill_path,
            license=skill.get("license"),
            compatibility=skill.get("compatibility"),
            metadata=metadata,
            allowed_tools=allowed_tools,
        )

    def clear_cache(self) -> None:
        """Clear the skills cache."""
        self._cache.clear()
        self._built_in_cache = None


__all__ = ["BasementMemoryLoader", "BasementSkillsLoader"]
