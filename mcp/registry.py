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
}