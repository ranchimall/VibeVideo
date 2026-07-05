MCP_REGISTRY = {

    "extract_audio": {
        "action": "extract_audio",
        "input": ["input_files"],
        "output": ["output_file"],
        "errors": [
            "file_not_found",
            "unsupported_format"
        ]
    },

    "take_screenshot": {
        "action": "take_screenshot",
        "input": ["input_files"],
        "output": ["output_file"],
        "errors": [
            "timestamp_out_of_range"
        ]
    },

    "normalize_audio": {
        "action": "normalize_audio",
        "input": ["input_files"],
        "output": ["output_file"],
        "errors": [
            "file_not_found"
        ]
    },

    "resize_video": {
        "action": "resize_video",
        "input": [
            "input_files",
            "width",
            "height"
        ],
        "output": [
            "output_file"
        ],
        "errors": [
            "unsupported_resolution",
            "file_not_found"
        ]
    },

    "download_youtube": {
        "action": "download_youtube",
        "input": [
            "url",
            "quality",
            "start_time",
            "end_time",
            "delete_full"
        ],
        "output": [
            "output_file"
        ],
        "errors": [
            "invalid_url",
            "download_failed",
            "trim_failed"
        ]
    },

    "face_swap_video": {
        "action": "face_swap_video",
        "input": [
            "input_files"
        ],
        "output": [
            "output_file"
        ],
        "errors": [
            "file_not_found"
        ]
    },

    "screen_record": {
        "action": "screen_record",
        "input": ["fps", "duration"],
        "output": ["output_file"],
        "errors": ["recording_failed"]
    },
    "screen_record_audio": {
        "action": "screen_record_audio",
        "input": ["fps", "duration"],
        "output": ["output_file"],
        "errors": ["recording_failed"]
    },
    "video_clip": {
        "action": "video_clip",
        "input": ["input_files", "start_time", "end_time", "duration"],
        "output": ["output_file"],
        "errors": ["file_not_found", "invalid_timestamp"]
    },
    "video_merge": {
        "action": "video_merge",
        "input": ["input_files", "transition"],
        "output": ["output_file"],
        "errors": ["file_not_found", "merge_failed"]
    },
    "audio_trim": {
        "action": "audio_trim",
        "input": ["input_files", "start_time", "end_time", "duration"],
        "output": ["output_file"],
        "errors": ["file_not_found", "invalid_timestamp"]
    },
    "audio_volume": {
        "action": "audio_volume",
        "input": ["input_files", "volume_level"],
        "output": ["output_file"],
        "errors": ["file_not_found"]
    },
    "audio_fade": {
        "action": "audio_fade",
        "input": ["input_files", "fade_type", "fade_duration", "start_time"],
        "output": ["output_file"],
        "errors": ["file_not_found"]
    },
    "audio_mix": {
        "action": "audio_mix",
        "input": ["input_files"],
        "output": ["output_file"],
        "errors": ["file_not_found", "mix_failed"]
    },
    "audio_speed": {
        "action": "audio_speed",
        "input": ["input_files", "speed_multiplier"],
        "output": ["output_file"],
        "errors": ["file_not_found"]
    },
    "audio_reverse": {
        "action": "audio_reverse",
        "input": ["input_files"],
        "output": ["output_file"],
        "errors": ["file_not_found"]
    },
    "audio_replace": {
        "action": "audio_replace",
        "input": ["input_files"],
        "output": ["output_file"],
        "errors": ["file_not_found"]
    },
    "audio_visual": {
        "action": "audio_visual",
        "input": ["input_files", "visual_type"],
        "output": ["output_file"],
        "errors": ["file_not_found"]
    },
}