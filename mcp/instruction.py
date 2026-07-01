
from pathlib import Path
from mcp.registry import MCP_REGISTRY


def find_mcp_instruction(capability, params):

    spec = MCP_REGISTRY[capability]

    output_file = params["output_file"]

    return {

        "action": spec["action"],

        "input": {

            key: params.get(key)

            for key in spec["input"]

        },

        "output": {

            "output_file": output_file

        },

        "errors": spec["errors"]

    }