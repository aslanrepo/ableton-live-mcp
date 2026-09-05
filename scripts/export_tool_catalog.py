"""Export the full tool contract as deterministic JSON, without connecting to Live."""

import argparse
import ast
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("ABLETON_TOOLSETS", None)

from ableton_live_mcp import __version__, tools  # noqa: E402, F401
from ableton_live_mcp.app import mcp  # noqa: E402
from ableton_live_mcp.tools._groups import GROUP_MODULES  # noqa: E402


def catalogue():
    groups = {}
    for group, modules in GROUP_MODULES.items():
        for module in modules:
            tree = ast.parse((ROOT / "ableton_live_mcp/tools" / f"{module}.py").read_text())
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    groups[node.name] = group
    entries = []
    for tool in sorted(asyncio.run(mcp.list_tools()), key=lambda item: item.name):
        entries.append(
            {
                "name": tool.name,
                "group": groups[tool.name],
                "description": tool.description,
                "inputSchema": tool.inputSchema,
                "annotations": tool.annotations.model_dump(exclude_none=True)
                if tool.annotations
                else {},
            }
        )
    return {"version": __version__, "toolCount": len(entries), "tools": entries}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(catalogue(), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")
