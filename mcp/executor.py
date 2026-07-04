"""
Central dispatcher: takes the {tool, implementation} dict produced by
capability_resolver.resolve_tool() plus the MCP instruction, and routes
it to the right engine. This replaces per-tool if/elif branches that
would otherwise pile up wherever resolve_tool() is called.
"""

from engines.ffmpeg_engine import execute_ffmpeg
from engines.youtube_engine import execute_youtube


ENGINE_DISPATCH = {
    "ffmpeg": execute_ffmpeg,
    "yt_dlp": execute_youtube,
}


def execute(tool, instruction):
    """
    tool: dict from resolve_tool(), e.g. {"tool": "ffmpeg", "implementation": "resize_video"}
    instruction: dict from find_mcp_instruction()

    Returns whatever the underlying engine returns (typically an output path),
    or raises if the tool is unknown or the engine call fails.
    """

    if tool is None:
        raise ValueError("No tool resolved for this instruction.")

    engine_fn = ENGINE_DISPATCH.get(tool["tool"])

    if engine_fn is None:
        raise ValueError(f"No engine registered for tool: {tool['tool']!r}")

    return engine_fn(tool["implementation"], instruction)