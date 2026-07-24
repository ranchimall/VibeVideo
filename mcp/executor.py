"""
Central dispatcher: takes the {tool, implementation} dict produced by
capability_resolver.resolve_tool() plus the MCP instruction, and routes
it to the right engine. This replaces per-tool if/elif branches that
would otherwise pile up wherever resolve_tool() is called.
"""

from engines.ffmpeg_engine import execute_ffmpeg
from engines.youtube_engine import execute_youtube
from engines.audacity_engine import execute_audacity
from engines.insightface_engine import execute_insightface
from engines.cv_text_engine import execute_cv
from engines.cv_object_engine import execute_cv_object
from engines.whisper_engine import execute_whisper

def execute_cv_dispatcher(implementation, instruction, has_gpu=False):
    if implementation == "object_replace_video":
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if has_gpu:
            # SAM2 + ProPainter pipeline -- needs CUDA, higher quality/consistency.
            from engines.cv_object_engine_v2 import execute_cv_object_v2
            return execute_cv_object_v2(instruction, ffmpeg_path)
        # YOLO + ByteTrack pipeline -- CPU-usable fallback.
        return execute_cv_object(instruction, ffmpeg_path)
    return execute_cv(implementation, instruction)

ENGINE_DISPATCH = {
    "ffmpeg": execute_ffmpeg,
    "yt_dlp": execute_youtube,
    "audacity": execute_audacity,
    "insightface": execute_insightface,
    "cv": execute_cv_dispatcher,
    "whisper": execute_whisper,
}


def execute(tool, instruction, has_gpu=False):
    """
    tool: dict from resolve_tool(), e.g. {"tool": "ffmpeg", "implementation": "resize_video"}
    instruction: dict from find_mcp_instruction()
    has_gpu: whether a CUDA GPU is available -- only affects the "cv" tool
             (specifically object_replace_video); every other engine call is
             identical regardless of this flag.

    Returns whatever the underlying engine returns (typically an output path),
    or raises if the tool is unknown or the engine call fails.
    """

    if tool is None:
        raise ValueError("No tool resolved for this instruction.")

    engine_fn = ENGINE_DISPATCH.get(tool["tool"])

    if engine_fn is None:
        raise ValueError(f"No engine registered for tool: {tool['tool']!r}")

    if tool["tool"] == "cv":
        return engine_fn(tool["implementation"], instruction, has_gpu)

    return engine_fn(tool["implementation"], instruction)