"""
Tier 1 multicommand executor.

A multicommand is a registered, named sequence of MCP capability steps
(see multi_registry.py). Each step declares where its parameters come
from, so branching pipelines (e.g. one video splitting into two
differently-captioned outputs) are supported, not just straight chains.

Each step is executed through the SAME find_mcp_instruction -> resolve_tool
-> execute path that single commands use, so whisper/ffmpeg/etc engines
don't need to know anything about multicommands at all.
"""

import re

from mcp.instruction import find_mcp_instruction
from mcp.capability_resolver import resolve_tool
from mcp.executor import execute as execute_tool_instruction
from multicommand.multi_registry import MULTI_REGISTRY
from multicommand.multi_helpers import HELPERS


def _cast(value, cast):
    if value is None or cast is None:
        return value
    if cast == "float":
        return float(value)
    if cast == "int":
        return int(float(value))
    return value


def _resolve_file_ref(ref, ctx):
    """Resolve the 'on' field of a computed param spec: either the
    original input video, or an earlier step's (single) output file."""
    if ref == "original_input":
        files = ctx["original_input_files"]
        if not files:
            raise ValueError("Multicommand needs an input video but none was found in the query.")
        return files[0]

    out = ctx["step_outputs"].get(ref)
    if out is None:
        raise ValueError(f"Step '{ref}' has no output yet (check step order in the multicommand definition).")
    return out[0] if isinstance(out, list) else out


def _resolve_param(spec, ctx):
    source = spec["source"]

    if source == "fixed":
        return spec["value"]

    if source == "regex":
        m = re.search(spec["pattern"], ctx["raw_query"], re.I)
        if not m:
            return spec.get("default")
        return _cast(m.group(spec.get("group", 1)), spec.get("cast"))

    if source == "original_input":
        return list(ctx["original_input_files"])

    if source == "step_output_list":
        out = ctx["step_outputs"].get(spec["step"])
        if out is None:
            raise ValueError(f"Step '{spec['step']}' has no output yet.")
        return [out] if isinstance(out, str) else list(out)

    if source == "step_outputs":
        files = []
        for step_id in spec["steps"]:
            out = ctx["step_outputs"].get(step_id)
            if out is None:
                raise ValueError(f"Step '{step_id}' has no output yet.")
            files.extend(out if isinstance(out, list) else [out])
        return files

    if source == "computed":
        func = HELPERS.get(spec["func"])
        if func is None:
            raise ValueError(f"Unknown computed helper: {spec['func']!r}")
        file_ref = _resolve_file_ref(spec["on"], ctx)
        return func(file_ref)

    raise ValueError(f"Unknown param source type: {source!r}")


def _run_step(step, ctx):
    capability = step["capability"]

    resolved = {key: _resolve_param(spec, ctx) for key, spec in step["params"].items()}
    resolved["output_file"] = step.get("output_file")

    instruction = find_mcp_instruction(capability, resolved)
    tool = resolve_tool(instruction)

    print(f"\n[multicommand] Step '{step['id']}' -> {capability}")
    print(f"  params: { {k: v for k, v in resolved.items() if k != 'output_file'} }")

    if tool is None:
        raise ValueError(f"No tool resolved for capability '{capability}'.")

    output = execute_tool_instruction(tool, instruction)
    ctx["step_outputs"][step["id"]] = output
    print(f"  -> {output}")
    return output


def execute_multicommand(name, raw_query, original_input_files):
    """
    name: key into MULTI_REGISTRY
    raw_query: the user's (preprocessed) query text, used for per-step regex extraction
    original_input_files: list of media files the top-level query was resolved to reference

    Returns the list of outputs from steps marked "final": True.
    """
    if name not in MULTI_REGISTRY:
        raise ValueError(f"Unknown multicommand: {name!r}")

    definition = MULTI_REGISTRY[name]
    ctx = {
        "raw_query": raw_query,
        "original_input_files": original_input_files,
        "step_outputs": {},
    }

    print(f"\nRunning multicommand '{name}': {definition.get('description', '')}")

    final_outputs = []
    for step in definition["steps"]:
        try:
            output = _run_step(step, ctx)
        except Exception as e:
            raise RuntimeError(f"Multicommand '{name}' failed at step '{step['id']}': {e}") from e
        if step.get("final"):
            final_outputs.append(output)

    return final_outputs