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
import os
from mcp.instruction import find_mcp_instruction
from mcp.capability_resolver import resolve_tool
from mcp.executor import execute as execute_tool_instruction
from multicommand.multi_registry import MULTI_REGISTRY
from multicommand.multi_helpers import HELPERS, REPEAT_SOURCES


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

    if source == "repeat_value":
        # Only valid inside a "repeat" step -- pulls a field out of the
        # current repetition's item (see _run_repeat_step).
        item = ctx.get("repeat_item")
        if item is None:
            raise ValueError("'repeat_value' source used outside of a repeat step.")
        return item[spec["field"]]

    raise ValueError(f"Unknown param source type: {source!r}")

def _format_output_name(template, video_path, index, total):
    """Fill {base}/{ext}/{index}/{total} placeholders in an
    output_file_template using the reference video's name."""
    base, ext = os.path.splitext(os.path.basename(video_path))
    return template.format(base=base, ext=ext, index=index, total=total)

def _run_step(step, ctx):
    capability = step["capability"]

    resolved = {key: _resolve_param(spec, ctx) for key, spec in step["params"].items()}

    if step.get("output_file_template"):
        ref_video = ctx["original_input_files"][0] if ctx["original_input_files"] else None
        resolved["output_file"] = (
            _format_output_name(step["output_file_template"], ref_video, index=1, total=1)
            if ref_video else None
        )
    else:
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

def _run_repeat_step(step, ctx):
    """Run the same capability once per item produced by a REPEAT_SOURCES
    helper (e.g. once per "from X to Y" range found in the query), instead
    of once total like a normal step. Each repetition's output is stored
    under '<step_id>_<n>' (1-based) in ctx['step_outputs'], and the full
    list of outputs is returned so the caller can flatten it into
    final_outputs.

    Needs an 'output_file_template' on the step (with {base}/{ext}/{index}/
    {total} placeholders) since the underlying capability's own default
    naming would otherwise reuse the same filename for every repetition.
    """
    repeat_spec = step["repeat"]
    source_fn = REPEAT_SOURCES.get(repeat_spec["over"])
    if source_fn is None:
        raise ValueError(f"Unknown repeat source: {repeat_spec['over']!r}")

    video_path = _resolve_file_ref(repeat_spec.get("on", "original_input"), ctx)
    items = source_fn(ctx["raw_query"], video_path)

    if not items:
        raise ValueError(
            f"Step '{step['id']}': found no repetitions to run (e.g. no "
            f"'from X to Y' ranges were found in the query)."
        )

    template = step.get("output_file_template")
    if not template:
        raise ValueError(f"Step '{step['id']}': a repeat step requires 'output_file_template'.")

    capability = step["capability"]
    outputs = []

    for i, item in enumerate(items, start=1):
        ctx["repeat_item"] = item

        resolved = {key: _resolve_param(spec, ctx) for key, spec in step["params"].items()}
        resolved["output_file"] = _format_output_name(template, video_path, i, len(items))

        instruction = find_mcp_instruction(capability, resolved)
        tool = resolve_tool(instruction)

        print(f"\n[multicommand] Step '{step['id']}' [{i}/{len(items)}] -> {capability}")
        print(f"  params: { {k: v for k, v in resolved.items() if k != 'output_file'} }")

        if tool is None:
            raise ValueError(f"No tool resolved for capability '{capability}'.")

        output = execute_tool_instruction(tool, instruction)
        ctx["step_outputs"][f"{step['id']}_{i}"] = output
        print(f"  -> {output}")
        outputs.append(output)

    ctx.pop("repeat_item", None)
    ctx["step_outputs"][step["id"]] = outputs
    return outputs

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
            if step.get("repeat"):
                output = _run_repeat_step(step, ctx)
            else:
                output = _run_step(step, ctx)
        except Exception as e:
            raise RuntimeError(f"Multicommand '{name}' failed at step '{step['id']}': {e}") from e
        if step.get("final"):
            if isinstance(output, list):
                final_outputs.extend(output)
            else:
                final_outputs.append(output)

    return final_outputs