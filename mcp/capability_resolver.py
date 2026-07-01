CAPABILITY_TOOL_MAP = {

    "extract_audio": {

        "tool": "ffmpeg",

        "implementation": "extract_audio"

    },

    "take_screenshot": {

        "tool": "ffmpeg",

        "implementation": "take_screenshot"

    },

    "normalize_audio": {

        "tool": "audacity",

        "implementation": "normalize_audio"

    },

        "resize_video": {

        "tool": "ffmpeg",

        "implementation": "resize_video"

    }

}

def resolve_tool(instruction):

    action = instruction["action"]

    return CAPABILITY_TOOL_MAP.get(action)