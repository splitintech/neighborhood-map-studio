"""Bounded image decoder. Invoked in a credential-free child process, never imported by routes."""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import warnings

MAX_INPUT = 5 * 1024 * 1024
MAX_PIXELS = 16_777_216


def process_image(raw: bytes, mime: str) -> tuple[bytes, int, int]:
    from PIL import Image, ImageOps
    if not raw or len(raw) > MAX_INPUT:
        raise ValueError("image_size_invalid")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    if mime == "image/svg+xml":
        from defusedxml import ElementTree
        root = ElementTree.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ValueError("svg_root_invalid")
        view_box = root.get("viewBox", "").replace(",", " ").split()
        if len(view_box) == 4:
            svg_width, svg_height = float(view_box[2]), float(view_box[3])
        else:
            def dimension(name):
                value = root.get(name, "")
                if not re.fullmatch(r"\d+(?:\.\d+)?(?:px)?", value):
                    raise ValueError("svg_dimensions_required")
                return float(value.removesuffix("px"))
            svg_width, svg_height = dimension("width"), dimension("height")
        import math
        if not all(math.isfinite(v) and 0 < v <= 8192 for v in (svg_width, svg_height)):
            raise ValueError("svg_dimensions_invalid")
        scale = min(1, 2048 / max(svg_width, svg_height))
        allowed = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
                   "polygon", "defs", "linearGradient", "radialGradient", "stop",
                   "clipPath", "title", "desc"}
        nodes = list(root.iter())
        if len(nodes) > 10_000:
            raise ValueError("svg_complexity_limit")
        for node in nodes:
            if node.tag.rsplit("}", 1)[-1] not in allowed:
                raise ValueError("svg_active_or_external_content")
            for key, value in node.attrib.items():
                key = key.rsplit("}", 1)[-1].lower()
                if key.startswith("on") or key in {"href", "src", "base"}:
                    raise ValueError("svg_active_or_external_content")
                if "@import" in value.lower() or "expression(" in value.lower():
                    raise ValueError("svg_active_or_external_content")
                for target in re.findall(r"url\s*\((.*?)\)", value, re.I):
                    if not re.fullmatch(r"#[A-Za-z_][\w.-]*", target.strip("\"' ")):
                        raise ValueError("svg_external_resource")
        # Disable network access even if a future decoder change introduces a fetch.
        import cairosvg
        import socket
        def deny_network(*_args, **_kwargs):
            raise ValueError("image_network_forbidden")
        socket.socket = deny_network
        raw = cairosvg.svg2png(bytestring=raw, output_width=max(1, round(svg_width * scale)),
                              output_height=max(1, round(svg_height * scale)), unsafe=False)
    elif mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("image_type_invalid")
    image = Image.open(io.BytesIO(raw))
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
    if mime in expected and image.format != expected[mime]:
        raise ValueError("image_signature_mismatch")
    if image.width * image.height > MAX_PIXELS or max(image.size) > 8192:
        raise ValueError("image_dimensions_invalid")
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("animated_images_not_supported")
    image.load()
    image = ImageOps.exif_transpose(image).convert("RGBA")
    image.thumbnail((2048, 2048))
    output = io.BytesIO()
    image.save(output, format="WEBP", quality=90, method=4)
    return output.getvalue(), image.width, image.height


def main() -> None:
    if sys.platform == "linux":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
    try:
        request = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024 + 1))
        raw = base64.b64decode(request["dataBase64"], validate=True)
        image, width, height = process_image(raw, request["mimeType"])
        print(json.dumps({"dataBase64": base64.b64encode(image).decode(),
                          "width": width, "height": height}))
    except Exception:
        # Parser errors can contain user data. Return a fixed, non-sensitive error.
        print(json.dumps({"error": "image_rejected"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
