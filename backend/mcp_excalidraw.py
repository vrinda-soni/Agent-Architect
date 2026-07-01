"""
Excalidraw MCP Server
---------------------
Exposes architecture diagram creation as MCP tools.
Run (stdio): python -m backend.mcp_excalidraw
"""
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import json
import base64
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("excalidraw")


@mcp.tool()
def create_architecture_diagram(
    nodes: list[dict],
    edges: list[dict],
    title: str = "Architecture Diagram",
) -> dict:
    """
    Create an Excalidraw architecture diagram from nodes and edges.

    Node schema: {"id": str, "label": str, "type": "box"|"circle"|"database"|"decision", "layer": int}
    Edge schema: {"from": str, "to": str, "label": str}

    Returns the Excalidraw scene JSON and a local interactive URL
    (requires the FastAPI backend to be running on port 8000).
    """
    from backend.excalidraw_utils import build_excalidraw_json

    scene = build_excalidraw_json({"nodes": nodes, "edges": edges})
    encoded = base64.urlsafe_b64encode(json.dumps(scene).encode()).decode()
    local_url = f"http://localhost:8000/diagram?data={encoded}"

    return {
        "title": title,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "scene_json": scene,
        "local_url": local_url,
    }


@mcp.tool()
def render_diagram_png(nodes: list[dict], edges: list[dict]) -> str:
    """
    Render an architecture diagram to a base64-encoded PNG.

    Requires Playwright + Chromium to be installed.
    Returns empty string if rendering fails.

    Node schema: {"id": str, "label": str, "type": str, "layer": int}
    Edge schema: {"from": str, "to": str, "label": str}
    """
    from backend.excalidraw_utils import build_excalidraw_json, excalidraw_to_png

    scene = build_excalidraw_json({"nodes": nodes, "edges": edges})
    png_bytes = excalidraw_to_png(scene)
    if png_bytes:
        return base64.b64encode(png_bytes).decode()
    return ""


@mcp.tool()
def scene_to_interactive_url(scene_json: dict) -> str:
    """
    Convert an existing Excalidraw scene JSON dict to a local interactive URL.
    Requires the FastAPI backend to be running on port 8000.
    """
    encoded = base64.urlsafe_b64encode(json.dumps(scene_json).encode()).decode()
    return f"http://localhost:8000/diagram?data={encoded}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
