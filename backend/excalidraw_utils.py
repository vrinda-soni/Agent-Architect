"""
excalidraw_utils.py
-------------------
Converts a simple node/edge architecture description into:
1. A proper Excalidraw JSON scene (with auto-layout)
2. A PNG image via Playwright headless Chrome
"""

import io
import json
import uuid
import math
import tempfile
import os


# ── Colour palette (professional navy theme) ─────────────────────────────────

_COLOURS = [
    {"stroke": "#1E3A5F", "fill": "#DBEAFE"},  # navy / light blue
    {"stroke": "#065F46", "fill": "#D1FAE5"},  # green
    {"stroke": "#7C3AED", "fill": "#EDE9FE"},  # purple
    {"stroke": "#B45309", "fill": "#FEF3C7"},  # amber
    {"stroke": "#DC2626", "fill": "#FEE2E2"},  # red
    {"stroke": "#0369A1", "fill": "#E0F2FE"},  # sky
]


def _uid() -> str:
    return str(uuid.uuid4()).replace("-", "")[:16]


# ── Auto-layout: place nodes in layers left-to-right ─────────────────────────

def _auto_layout(nodes: list, edges: list):
    """Assign x,y positions to nodes using a simple layered layout."""
    BOX_W, BOX_H = 200, 60
    H_GAP, V_GAP = 140, 80

    # Group by layer (default 0)
    layers: dict[int, list] = {}
    for n in nodes:
        layer = n.get("layer", 0)
        layers.setdefault(layer, []).append(n)

    # Assign coords
    positions = {}
    for layer_idx, layer_key in enumerate(sorted(layers)):
        layer_nodes = layers[layer_key]
        total_h = len(layer_nodes) * BOX_H + (len(layer_nodes) - 1) * V_GAP
        start_y = -total_h / 2
        for i, node in enumerate(layer_nodes):
            x = layer_idx * (BOX_W + H_GAP)
            y = start_y + i * (BOX_H + V_GAP)
            positions[node["id"]] = (x, y, BOX_W, BOX_H)

    return positions


# ── Build Excalidraw JSON from nodes + edges ──────────────────────────────────

def build_excalidraw_json(diagram: dict) -> dict:
    """
    Convert simple node/edge dict to full Excalidraw scene JSON.

    diagram format:
    {
      "nodes": [{"id": "ui", "label": "User Interface", "type": "box", "layer": 0}],
      "edges": [{"from": "ui", "to": "api", "label": "HTTP"}]
    }
    """
    nodes = diagram.get("nodes", [])
    edges = diagram.get("edges", [])

    positions = _auto_layout(nodes, edges)
    elements = []
    elem_ids: dict[str, str] = {}  # node.id -> excalidraw element id

    for i, node in enumerate(nodes):
        nid = node["id"]
        if nid not in positions:
            continue
        x, y, w, h = positions[nid]
        colour = _COLOURS[i % len(_COLOURS)]
        eid = _uid()
        elem_ids[nid] = eid

        node_type = node.get("type", "box")
        shape_type = "diamond" if node_type == "decision" else \
                     "ellipse" if node_type in ("circle", "db", "database") else \
                     "rectangle"

        roundness = {"type": 3} if shape_type == "rectangle" else None

        el: dict = {
            "id": eid,
            "type": shape_type,
            "x": x, "y": y,
            "width": w, "height": h,
            "angle": 0,
            "strokeColor": colour["stroke"],
            "backgroundColor": colour["fill"],
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": roundness,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
        }
        elements.append(el)

        # Label text
        label = node.get("label", nid)
        text_id = _uid()
        elements.append({
            "id": text_id,
            "type": "text",
            "x": x + 10,
            "y": y + h / 2 - 10,
            "width": w - 20,
            "height": 20,
            "angle": 0,
            "strokeColor": colour["stroke"],
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
            "text": label,
            "fontSize": 14,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "containerId": eid,
            "originalText": label,
            "lineHeight": 1.25,
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
        })

    # Arrows
    for edge in edges:
        from_id = elem_ids.get(edge.get("from", ""))
        to_id   = elem_ids.get(edge.get("to", ""))
        if not from_id or not to_id:
            continue

        fp = positions.get(edge.get("from", ""))
        tp = positions.get(edge.get("to", ""))
        if not fp or not tp:
            continue

        fx, fy, fw, fh = fp
        tx, ty, tw, th = tp

        # Start at right edge of from, end at left edge of to
        sx = fx + fw
        sy = fy + fh / 2
        ex = tx
        ey = ty + th / 2

        arrow_id = _uid()
        elements.append({
            "id": arrow_id,
            "type": "arrow",
            "x": sx, "y": sy,
            "width": ex - sx,
            "height": ey - sy,
            "angle": 0,
            "strokeColor": "#475569",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": 2},
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
            "points": [[0, 0], [ex - sx, ey - sy]],
            "lastCommittedPoint": None,
            "startBinding": {"elementId": from_id, "gap": 4, "focus": 0},
            "endBinding":   {"elementId": to_id,   "gap": 4, "focus": 0},
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "version": 1,
            "versionNonce": 1,
            "isDeleted": False,
        })

        # Edge label
        label = edge.get("label", "")
        if label:
            lx = (sx + ex) / 2 - 40
            ly = (sy + ey) / 2 - 10
            elements.append({
                "id": _uid(),
                "type": "text",
                "x": lx, "y": ly,
                "width": 80, "height": 16,
                "angle": 0,
                "strokeColor": "#64748B",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "roughness": 1,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": None,
                "boundElements": [],
                "updated": 1,
                "link": None,
                "locked": False,
                "text": label,
                "fontSize": 11,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": None,
                "originalText": label,
                "lineHeight": 1.25,
                "version": 1,
                "versionNonce": 1,
                "isDeleted": False,
            })

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": None,
            "viewBackgroundColor": "#ffffff",
        },
        "files": {},
    }


# ── PIL render: node/edge diagram → PNG (no CDN, no browser needed) ──────────

def diagram_to_png(diagram: dict, width: int = 1400, height: int = 800) -> bytes | None:
    """
    Render a node/edge architecture diagram to PNG using Pillow.
    No internet or browser required — works in any environment.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        nodes = diagram.get("nodes", [])
        edges = diagram.get("edges", [])
        if not nodes:
            return None

        # ── Layout constants ─────────────────────────────────────────────────
        BOX_W, BOX_H = 190, 65
        H_GAP  = 230   # centre-to-centre horizontal spacing
        V_GAP  = 100   # centre-to-centre vertical spacing
        MARGIN = 80

        # Group nodes by layer
        layers: dict[int, list] = {}
        for n in nodes:
            layers.setdefault(n.get("layer", 0), []).append(n)

        max_layer    = max(layers.keys()) if layers else 0
        max_per_col  = max(len(v) for v in layers.values()) if layers else 1

        # Dynamic canvas
        canvas_w = max(width,  MARGIN * 2 + max_layer * H_GAP + BOX_W)
        canvas_h = max(height, MARGIN * 2 + (max_per_col - 1) * V_GAP + BOX_H)

        img  = Image.new("RGB", (canvas_w, canvas_h), (248, 250, 252))  # very light grey bg
        draw = ImageDraw.Draw(img)

        # ── Fonts ─────────────────────────────────────────────────────────────
        _FONT_PATHS = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        _FONT_REG_PATHS = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        def _load_font(paths, size):
            for p in paths:
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        font_bold  = _load_font(_FONT_PATHS,     13)
        font_small = _load_font(_FONT_REG_PATHS, 10)
        font_title = _load_font(_FONT_PATHS,     11)

        # ── Node-type colours ─────────────────────────────────────────────────
        _TYPE_COLOURS = {
            "box":      ("#1E3A5F", "#DBEAFE"),
            "database": ("#065F46", "#D1FAE5"),
            "decision": ("#92400E", "#FEF3C7"),
            "circle":   ("#6B21A8", "#EDE9FE"),
            "cloud":    ("#0369A1", "#E0F2FE"),
        }
        _DEFAULT_COLOUR = ("#1E3A5F", "#DBEAFE")

        def _hex(h):
            h = h.lstrip("#")
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

        # ── Compute node centres ──────────────────────────────────────────────
        positions: dict[str, tuple] = {}
        for layer_idx, layer_nodes in sorted(layers.items()):
            n = len(layer_nodes)
            total_h = (n - 1) * V_GAP + BOX_H
            y_start = (canvas_h - total_h) // 2 + BOX_H // 2
            x_c = MARGIN + BOX_W // 2 + layer_idx * H_GAP
            for i, node in enumerate(layer_nodes):
                positions[node["id"]] = (x_c, y_start + i * V_GAP)

        # ── Draw edges ────────────────────────────────────────────────────────
        _ARROW_CLR = (100, 116, 139)   # slate-500

        def _draw_arrow(x1, y1, x2, y2):
            draw.line([(x1, y1), (x2, y2)], fill=_ARROW_CLR, width=2)
            angle  = math.atan2(y2 - y1, x2 - x1)
            alen, aspread = 14, 0.38
            for sign in (aspread, -aspread):
                ax = x2 - alen * math.cos(angle - sign)
                ay = y2 - alen * math.sin(angle - sign)
                draw.line([(x2, y2), (int(ax), int(ay))], fill=_ARROW_CLR, width=2)

        for edge in edges:
            src, dst = edge.get("from"), edge.get("to")
            if src not in positions or dst not in positions:
                continue
            sx, sy = positions[src]
            dx, dy = positions[dst]
            # Connect right-edge → left-edge when source is to the left
            if sx < dx - BOX_W * 0.4:
                start = (sx + BOX_W // 2, sy)
                end   = (dx - BOX_W // 2, dy)
            else:
                start = (sx, sy + BOX_H // 2)
                end   = (dx, dy - BOX_H // 2)
            _draw_arrow(*start, *end)
            lbl = edge.get("label", "")
            if lbl:
                mx = (start[0] + end[0]) // 2
                my = (start[1] + end[1]) // 2 - 12
                bbox = draw.textbbox((0, 0), lbl, font=font_small)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.rectangle([mx - tw//2 - 4, my - 2, mx + tw//2 + 4, my + th + 2],
                               fill=(255, 255, 255))
                draw.text((mx - tw//2, my), lbl, fill=(100, 116, 139), font=font_small)

        # ── Draw nodes ────────────────────────────────────────────────────────
        for node in nodes:
            nid   = node.get("id")
            label = node.get("label", nid or "")
            ntype = node.get("type", "box")
            if nid not in positions:
                continue
            cx, cy = positions[nid]
            x0, y0 = cx - BOX_W // 2, cy - BOX_H // 2
            x1, y1 = cx + BOX_W // 2, cy + BOX_H // 2
            stroke_hex, fill_hex = _TYPE_COLOURS.get(ntype, _DEFAULT_COLOUR)
            stroke_rgb = _hex(stroke_hex)
            fill_rgb   = _hex(fill_hex)

            draw.rounded_rectangle([x0, y0, x1, y1], radius=10,
                                   fill=fill_rgb, outline=stroke_rgb, width=2)

            # Word-wrap label into max 2 lines
            words = label.split()
            if len(words) <= 1 or len(label) <= 16:
                lines_lbl = [label]
            else:
                mid = max(1, len(words) // 2)
                lines_lbl = [" ".join(words[:mid]), " ".join(words[mid:])]

            line_h = 16
            total_text_h = len(lines_lbl) * line_h
            ty = cy - total_text_h // 2
            for ln in lines_lbl:
                bb = draw.textbbox((0, 0), ln, font=font_bold)
                tw = bb[2] - bb[0]
                draw.text((cx - tw // 2, ty), ln, fill=stroke_rgb, font=font_bold)
                ty += line_h

        # ── Legend (layer labels if meaningful) ───────────────────────────────
        if max_layer >= 2:
            layer_names = {0: "Client", 1: "Service", 2: "Backend", 3: "Data", 4: "External"}
            for layer_idx in sorted(layers.keys()):
                lname = layer_names.get(layer_idx, f"Layer {layer_idx}")
                x_c = MARGIN + BOX_W // 2 + layer_idx * H_GAP
                bb = draw.textbbox((0, 0), lname, font=font_small)
                tw = bb[2] - bb[0]
                draw.text((x_c - tw // 2, 16), lname, fill=(148, 163, 184), font=font_small)

        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(150, 150))
        buf.seek(0)
        return buf.read()

    except Exception as e:
        print(f"[Diagram] PIL render failed: {e}")
        return None


# ── Playwright render: Excalidraw JSON → PNG ──────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#ffffff; overflow:hidden; width:1400px; height:900px; }
  #root { width:1400px; height:900px; position:relative; }
  .excalidraw { background:#ffffff !important; }
</style>
</head>
<body>
<div id="root"></div>
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@excalidraw/excalidraw/dist/excalidraw.production.min.js"></script>
<script>
var SCENE = {scene_json};

var App = function() {
  var ref = React.useRef(null);
  React.useEffect(function() {
    if (ref.current) {
      ref.current.updateScene(SCENE);
      ref.current.scrollToContent(SCENE.elements, { fitFactor: 0.85, animate: false });
    }
  }, []);
  return React.createElement(ExcalidrawLib.Excalidraw, {
    excalidrawAPI: function(api) { ref.current = api; },
    initialData: SCENE,
    viewModeEnabled: true,
    zenModeEnabled: true,
    gridModeEnabled: false,
    UIOptions: {
      canvasActions: { export: false, loadScene: false, saveAsImage: false, changeViewBackgroundColor: false },
      tools: { image: false }
    }
  });
};

ReactDOM.render(React.createElement(App), document.getElementById('root'));
</script>
</body>
</html>"""


def excalidraw_to_png(excalidraw_json: dict) -> bytes | None:
    """Render Excalidraw JSON to PNG via Playwright headless Chrome."""
    try:
        from playwright.sync_api import sync_playwright

        scene_str = json.dumps(excalidraw_json)
        html_content = _HTML_TEMPLATE.replace("{scene_json}", scene_str)

        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False, encoding="utf-8") as f:
            f.write(html_content)
            tmp_path = f.name

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                page.goto(f"file://{tmp_path}", wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)  # let Excalidraw render
                png_bytes = page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1400, "height": 900},
                    full_page=False,
                )
                browser.close()
                return png_bytes
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print(f"[Excalidraw] Playwright render failed: {e}")
        return None
