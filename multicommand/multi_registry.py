"""
MULTI_REGISTRY: Tier 1 registered multicommands.

Each multicommand is a NAME -> {"description": ..., "steps": [...]}.
The NAME must exactly match the first line of its matching chunk in
multicommand_documents/multicommands.txt (same convention as the
capability/action name pattern used in documents/*.txt for single
commands).

Each step is:
    {
        "id": "<unique step id within this multicommand>",
        "capability": "<an MCP_REGISTRY key, e.g. 'video_clip'>",
        "params": {
            "<param name>": <param spec>,
            ...
        },
        "output_file": "<optional fixed output filename; omit to let the
                          underlying capability pick its own default>",
        "final": True/False   # marks this step's output as one of the
                               # multicommand's reported final results
    }

A param spec is one of:
    {"source": "fixed", "value": <any>}
        A literal value.

    {"source": "regex", "pattern": r"...", "group": 1, "cast": "float"|"int", "default": <any>}
        Extracted directly from the raw (preprocessed) user query text.

    {"source": "original_input"}
        The list of media files the top-level query was resolved to
        reference (usually the single video being operated on).

    {"source": "step_output_list", "step": "<step id>"}
        Wraps a single earlier step's output into a 1-item list (for
        params like input_files that expect a list).

    {"source": "step_outputs", "steps": ["<step id>", ...]}
        Combines multiple earlier steps' outputs into one input_files
        list (e.g. a clip + its .srt for burn_subtitles).

    {"source": "computed", "func": "<name in multi_helpers.HELPERS>", "on": "original_input" | "<step id>"}
        Calls a helper function (e.g. midpoint) against either the
        original input video or an earlier step's output file.
"""

MULTI_REGISTRY = {

    "subtitle_and_clip": {
        "description": "Clip a time range from a video and burn English subtitles onto it.",
        "steps": [
            {
                "id": "clip1",
                "capability": "video_clip",
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {
                        "source": "regex",
                        "pattern": r"\bfrom\s+(\d{1,2}:\d{2}(?::\d{2})?|\d+(?:\.\d+)?)\b",
                        "group": 1,
                    },
                    "end_time": {
                        "source": "regex",
                        "pattern": r"\bto\s+(\d{1,2}:\d{2}(?::\d{2})?|\d+(?:\.\d+)?)\b",
                        "group": 1,
                    },
                },
                "final": False,
            },
            {
                "id": "sub1",
                "capability": "generate_subtitles",
                "params": {
                    "input_files": {"source": "step_output_list", "step": "clip1"},
                    "language": {"source": "fixed", "value": "en"},
                    "task": {"source": "fixed", "value": "translate"},
                    "model": {"source": "fixed", "value": "base"},
                },
                "final": False,
            },
            {
                "id": "burn1",
                "capability": "burn_subtitles",
                "params": {
                    "input_files": {"source": "step_outputs", "steps": ["clip1", "sub1"]},
                },
                "final": True,
            },
        ],
    },

    "split_dual_subtitle": {
        "description": "Split a video in half and burn English subtitles on the first half, Hindi subtitles on the second half.",
        "steps": [
            {
                "id": "half1",
                "capability": "video_clip",
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {"source": "fixed", "value": 0},
                    "end_time": {"source": "computed", "func": "midpoint", "on": "original_input"},
                },
                "final": False,
            },
            {
                "id": "half2",
                "capability": "video_clip",
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {"source": "computed", "func": "midpoint", "on": "original_input"},
                    "end_time": {"source": "computed", "func": "duration", "on": "original_input"},
                },
                "final": False,
            },
            {
                "id": "sub_en",
                "capability": "generate_subtitles",
                "params": {
                    "input_files": {"source": "step_output_list", "step": "half1"},
                    "language": {"source": "fixed", "value": "en"},
                    "task": {"source": "fixed", "value": "translate"},
                    "model": {"source": "fixed", "value": "base"},
                },
                "final": False,
            },
            {
                "id": "burn_en",
                "capability": "burn_subtitles",
                "params": {
                    "input_files": {"source": "step_outputs", "steps": ["half1", "sub_en"]},
                },
                "final": True,
            },
            {
                "id": "sub_hi",
                "capability": "generate_subtitles",
                "params": {
                    "input_files": {"source": "step_output_list", "step": "half2"},
                    "language": {"source": "fixed", "value": "hi"},
                    "task": {"source": "fixed", "value": "transcribe"},
                    "model": {"source": "fixed", "value": "base"},
                },
                "final": False,
            },
            {
                "id": "burn_hi",
                "capability": "burn_subtitles",
                "params": {
                    "input_files": {"source": "step_outputs", "steps": ["half2", "sub_hi"]},
                },
                "final": True,
            },
        ],
    },


    "youtube_subtitles": {
        "description": "Download a YouTube video and generate subtitles for it.",
        "steps": [
            {
                "id": "dl1",
                "capability": "download_youtube",
                "params": {
                    "url": {
                        "source": "regex",
                        "pattern": r'(https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]+(?:[&?][^\s]*)?)',
                        "group": 1,
                    },
                },
                "final": True,
            },
            {
                "id": "sub1",
                "capability": "generate_subtitles",
                "params": {
                    "input_files": {"source": "step_output_list", "step": "dl1"},
                },
                "final": True,
            },
        ],
    },

    "youtube_to_mp3": {
        "description": "Download a YouTube video and convert it to an mp3 audio file.",
        "steps": [
            {
                "id": "dl1",
                "capability": "download_youtube",
                "params": {
                    "url": {
                        "source": "regex",
                        "pattern": r'(https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]+(?:[&?][^\s]*)?)',
                        "group": 1,
                    },
                },
                "final": False,
            },
            {
                "id": "mp3_1",
                "capability": "extract_audio",
                "params": {
                    "input_files": {"source": "step_output_list", "step": "dl1"},
                },
                "final": True,
            },
        ],
    },

    "multi_range_clip": {
        "description": "Clip several separate time ranges out of one video, one output file per range.",
        "steps": [
            {
                "id": "ranges",
                "capability": "video_clip",
                "repeat": {"over": "time_ranges", "on": "original_input"},
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {"source": "repeat_value", "field": "start"},
                    "end_time": {"source": "repeat_value", "field": "end"},
                },
                "output_file_template": "{base}_clip{index}{ext}",
                "final": True,
            },
        ],
    },

    "delete_time_ranges": {
        "description": "Delete one or more time ranges from a video, keeping everything else, merged into one output video.",
        "steps": [
            {
                "id": "keep",
                "capability": "video_clip",
                "repeat": {"over": "keep_segments", "on": "original_input"},
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {"source": "repeat_value", "field": "start"},
                    "end_time": {"source": "repeat_value", "field": "end"},
                },
                "output_file_template": "{base}_keep{index}{ext}",
                "final": False,
            },
            {
                "id": "merged",
                "capability": "video_merge",
                "params": {
                    "input_files": {"source": "step_outputs", "steps": ["keep"]},
                },
                "output_file_template": "{base}_deleted{ext}",
                "final": True,
            },
        ],
    },

    "delete_first_half": {
        "description": "Delete the first half of a video, keeping only the second half.",
        "steps": [
            {
                "id": "kept",
                "capability": "video_clip",
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {"source": "computed", "func": "midpoint", "on": "original_input"},
                    "end_time": {"source": "computed", "func": "duration", "on": "original_input"},
                },
                "final": True,
            },
        ],
    },

    "delete_second_half": {
        "description": "Delete the second half of a video, keeping only the first half.",
        "steps": [
            {
                "id": "kept",
                "capability": "video_clip",
                "params": {
                    "input_files": {"source": "original_input"},
                    "start_time": {"source": "fixed", "value": 0},
                    "end_time": {"source": "computed", "func": "midpoint", "on": "original_input"},
                },
                "final": True,
            },
        ],
    },
}    