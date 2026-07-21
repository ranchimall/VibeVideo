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

    },

    "download_youtube": {

        "tool": "yt_dlp",

        "implementation": "download_youtube"

    },

    "face_swap_video": {

        "tool": "insightface",

        "implementation": "face_swap_video"

    },
    
    "screen_record": {"tool": "ffmpeg", "implementation": "screen_record"},
    "screen_record_audio": {"tool": "ffmpeg", "implementation": "screen_record_audio"},
    "video_clip": {"tool": "ffmpeg", "implementation": "video_clip"},
    "video_merge": {"tool": "ffmpeg", "implementation": "video_merge"},
    "video_layer": {"tool": "ffmpeg", "implementation": "video_layer"},
    "video_replace_text": {"tool": "cv", "implementation": "video_replace_text"},
    "object_replace_video": {"tool": "cv", "implementation": "object_replace_video"},
    "audio_trim": {"tool": "ffmpeg", "implementation": "audio_trim"},
    "audio_volume": {"tool": "ffmpeg", "implementation": "audio_volume"},
    "audio_fade": {"tool": "ffmpeg", "implementation": "audio_fade"},
    "audio_mix": {"tool": "ffmpeg", "implementation": "audio_mix"},
    "audio_speed": {"tool": "ffmpeg", "implementation": "audio_speed"},
    "audio_reverse": {"tool": "ffmpeg", "implementation": "audio_reverse"},
    "audio_replace": {"tool": "ffmpeg", "implementation": "audio_replace"},
    "audio_visual": {"tool": "ffmpeg", "implementation": "audio_visual"},
    "generate_subtitles": {"tool": "whisper", "implementation": "generate_subtitles"},
    "burn_subtitles": {"tool": "whisper", "implementation": "burn_subtitles"},
    "clip_by_keyword": {"tool": "whisper", "implementation": "clip_by_keyword"},
    "clip_by_semantic": {"tool": "whisper", "implementation": "clip_by_semantic"},

}

def resolve_tool(instruction):

    action = instruction["action"]

    return CAPABILITY_TOOL_MAP.get(action)