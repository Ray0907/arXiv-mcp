"""Serve the bundled arXiv skill via the SEP-2640 Skills extension."""

import hashlib
import json
from importlib.resources import files

from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, RequestParams

_URI = "skill://arxiv/SKILL.md"
_DATA = files(__package__).joinpath("skill", "arxiv", "SKILL.md").read_bytes()
_TEXT = _DATA.decode("utf-8")
# shortcut: frontmatter is JSON-compatible YAML, use a YAML parser if richer syntax is needed.
_FRONTMATTER = json.loads(_TEXT.split("---\n", 2)[1])
_SKILL = {
    "uri": _URI,
    "frontmatter": _FRONTMATTER,
    "resources": [{"uri": _URI, "digest": "sha256:" + hashlib.sha256(_DATA).hexdigest(), "size": len(_DATA)}],
}
_CACHE = {"resultType": "complete", "ttlMs": 300_000, "cacheScope": "public"}
_PROTOCOLS = frozenset({"2026-07-28"})


# Validate skill-specific params after MethodBinding's protocol gate.
async def _list_skills(ctx: ServerRequestContext, _params: RequestParams):
    if (ctx.params or {}).get("cursor") is not None:
        raise MCPError(INVALID_PARAMS, "Unknown skills cursor")
    return {**_CACHE, "skills": [_SKILL]}


async def _get_skill(ctx: ServerRequestContext, _params: RequestParams):
    if (ctx.params or {}).get("uri") != _URI:
        raise MCPError(INVALID_PARAMS, "Unknown skill URI")
    return {**_CACHE, "skill": _SKILL}


class SkillsExtension(Extension):
    identifier = "io.modelcontextprotocol/skills"

    def resources(self):
        return (ResourceBinding(TextResource(
            uri=_URI, name=_FRONTMATTER["name"], description=_FRONTMATTER["description"],
            mime_type="text/markdown", text=_TEXT,
        )),)

    def methods(self):
        return (
            MethodBinding("skills/list", RequestParams, _list_skills, _PROTOCOLS),
            MethodBinding("skills/get", RequestParams, _get_skill, _PROTOCOLS),
        )
