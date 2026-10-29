import base64
import hashlib
import json
import math
import tempfile
from pathlib import Path

import cadquery as cq
import ezdxf
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from .schemas import (
    ArtifactPayload,
    CADOperation,
    ComponentKind,
    DesignRequirements,
    GenerateRequest,
    GenerateResponse,
    ValidationCheck,
)

SAFETY_NOTICE = (
    "Geometry validation is not structural analysis, code compliance, engineering "
    "certification, or approval for manufacturing."
)


def required_parameters(kind: ComponentKind) -> set[str]:
    return {
        ComponentKind.PLATE: {"length_mm", "width_mm", "thickness_mm"},
        ComponentKind.L_BRACKET: {"length_mm", "width_mm", "height_mm", "thickness_mm"},
        ComponentKind.SPACER: {"outer_diameter_mm", "inner_diameter_mm", "length_mm"},
        ComponentKind.ENCLOSURE: {"length_mm", "width_mm", "height_mm", "wall_thickness_mm"},
    }[kind]


def _hole_positions(length: float, width: float, count: int, diameter: float) -> list[tuple[float, float]]:
    if count == 0:
        return []
    edge = max(diameter, 2.0)
    if length <= edge * 2 or width <= edge * 2:
        raise ValueError("Part is too small for the requested hole diameter and edge distance")
    corners = [
        (-length / 2 + edge, -width / 2 + edge),
        (length / 2 - edge, -width / 2 + edge),
        (length / 2 - edge, width / 2 - edge),
        (-length / 2 + edge, width / 2 - edge),
    ]
    if count <= 4:
        return corners[:count]
    radius_x, radius_y = length / 2 - edge, width / 2 - edge
    return [
        (
            radius_x * math.cos(2 * math.pi * index / count),
            radius_y * math.sin(2 * math.pi * index / count),
        )
        for index in range(count)
    ]


def build_shape(requirements: DesignRequirements) -> tuple[cq.Workplane, list[CADOperation]]:
    missing = required_parameters(requirements.component_kind) - requirements.parameters.keys()
    if missing:
        raise ValueError(f"Missing required parameters: {', '.join(sorted(missing))}")
    p = requirements.parameters
    operations: list[CADOperation] = []

    if requirements.component_kind == ComponentKind.PLATE:
        length, width, thickness = p["length_mm"], p["width_mm"], p["thickness_mm"]
        shape = cq.Workplane("XY").box(length, width, thickness).translate((0, 0, thickness / 2))
        operations.append(
            CADOperation(
                operation="box",
                parameters={"length": length, "width": width, "height": thickness},
            )
        )
        shape, operations = _cut_holes(shape, requirements, length, width, thickness, operations)
    elif requirements.component_kind == ComponentKind.L_BRACKET:
        length, width = p["length_mm"], p["width_mm"]
        height, thickness = p["height_mm"], p["thickness_mm"]
        if thickness * 2 >= min(width, height):
            raise ValueError("Bracket thickness must be less than half its width and height")
        base = cq.Workplane("XY").box(length, width, thickness).translate((0, 0, thickness / 2))
        upright = (
            cq.Workplane("XY")
            .box(length, thickness, height)
            .translate((0, -width / 2 + thickness / 2, height / 2))
        )
        shape = base.union(upright)
        operations.extend(
            [
                CADOperation(
                    operation="box",
                    parameters={"length": length, "width": width, "height": thickness},
                ),
                CADOperation(
                    operation="union",
                    parameters={
                        "length": length,
                        "width": thickness,
                        "height": height,
                        "offset_y": -width / 2 + thickness / 2,
                    },
                ),
            ]
        )
        shape, operations = _cut_holes(shape, requirements, length, width, thickness, operations)
    elif requirements.component_kind == ComponentKind.SPACER:
        outer, inner, length = (
            p["outer_diameter_mm"],
            p["inner_diameter_mm"],
            p["length_mm"],
        )
        if inner >= outer:
            raise ValueError("Spacer inner diameter must be smaller than outer diameter")
        shape = cq.Workplane("XY").circle(outer / 2).extrude(length)
        operations.append(
            CADOperation(
                operation="cylinder",
                parameters={"diameter": outer, "height": length},
            )
        )
        if inner:
            shape = shape.faces(">Z").workplane().hole(inner, length)
            operations.append(
                CADOperation(
                    operation="hole",
                    parameters={"diameter": inner, "depth": length, "count": 1},
                )
            )
    else:
        length, width, height, wall = (
            p["length_mm"],
            p["width_mm"],
            p["height_mm"],
            p["wall_thickness_mm"],
        )
        if wall * 2 >= min(length, width, height):
            raise ValueError("Enclosure wall thickness is too large for its outer dimensions")
        outer = cq.Workplane("XY").box(length, width, height).translate((0, 0, height / 2))
        inner_height = height - wall + 1
        inner = (
            cq.Workplane("XY")
            .box(length - wall * 2, width - wall * 2, inner_height)
            .translate((0, 0, wall + inner_height / 2))
        )
        shape = outer.cut(inner)
        operations.extend(
            [
                CADOperation(
                    operation="box",
                    parameters={"length": length, "width": width, "height": height},
                ),
                CADOperation(
                    operation="cut",
                    parameters={
                        "length": length - wall * 2,
                        "width": width - wall * 2,
                        "height": inner_height,
                    },
                ),
            ]
        )

    fillet = p.get("fillet_radius_mm", 0)
    if fillet:
        if fillet >= min(value for value in p.values() if value > 0) / 2:
            raise ValueError("Fillet radius is too large for the part")
        try:
            shape = shape.edges("|Z").fillet(fillet)
            operations.append(CADOperation(operation="fillet", parameters={"radius": fillet}))
        except Exception as exc:
            raise ValueError("Requested fillet could not be applied to this geometry") from exc
    return shape, operations


def _cut_holes(
    shape: cq.Workplane,
    requirements: DesignRequirements,
    length: float,
    width: float,
    thickness: float,
    operations: list[CADOperation],
) -> tuple[cq.Workplane, list[CADOperation]]:
    if not requirements.hole_count:
        return shape, operations
    if not requirements.hole_diameter_mm:
        raise ValueError("Hole diameter is required when hole count is greater than zero")
    positions = _hole_positions(
        length, width, requirements.hole_count, requirements.hole_diameter_mm
    )
    for x, y in positions:
        cutter = (
            cq.Workplane("XY")
            .center(x, y)
            .circle(requirements.hole_diameter_mm / 2)
            .extrude(thickness + 2)
            .translate((0, 0, -1))
        )
        shape = shape.cut(cutter)
    operations.append(
        CADOperation(
            operation="hole",
            parameters={
                "diameter": requirements.hole_diameter_mm,
                "depth": thickness,
                "count": requirements.hole_count,
                "positions": [coordinate for pair in positions for coordinate in pair],
            },
        )
    )
    return shape, operations


def _artifact(kind: str, fmt: str, filename: str, media_type: str, data: bytes) -> ArtifactPayload:
    return ArtifactPayload(
        kind=kind,
        format=fmt,
        filename=filename,
        media_type=media_type,
        data_base64=base64.b64encode(data).decode(),
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )


def _mesh(shape: cq.Workplane, max_triangles: int) -> dict:
    vertices, triangles = shape.val().tessellate(0.2)
    if len(triangles) > max_triangles:
        vertices, triangles = shape.val().tessellate(0.8)
    if len(triangles) > max_triangles:
        raise ValueError("Preview mesh exceeds the configured triangle budget")
    return {
        "vertices": [[round(vertex.x, 5), round(vertex.y, 5), round(vertex.z, 5)] for vertex in vertices],
        "triangles": [list(triangle) for triangle in triangles],
    }


def _drawing_pdf(requirements: DesignRequirements, bbox: cq.BoundBox, revision: int) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        path = Path(handle.name)
    try:
        page = landscape(A4)
        drawing = canvas.Canvas(str(path), pagesize=page)
        width, height = page
        drawing.setTitle(f"{requirements.component_name} revision {revision}")
        drawing.setLineWidth(1)
        drawing.rect(24, 24, width - 48, height - 48)
        drawing.setFont("Helvetica-Bold", 15)
        drawing.drawString(42, height - 52, requirements.component_name)
        drawing.setFont("Helvetica", 8)
        drawing.drawRightString(width - 42, height - 48, f"REVISION {revision}")
        drawing.drawRightString(width - 42, height - 60, "UNITS: mm")

        views = [
            ("TOP", bbox.xlen, bbox.ylen, 70, 280),
            ("FRONT", bbox.xlen, bbox.zlen, 330, 280),
            ("SIDE", bbox.ylen, bbox.zlen, 590, 280),
        ]
        for label, view_w, view_h, x, y in views:
            scale = min(190 / max(view_w, 1), 145 / max(view_h, 1))
            rendered_w, rendered_h = view_w * scale, view_h * scale
            drawing.setFont("Helvetica-Bold", 9)
            drawing.drawString(x, y + 168, label)
            drawing.rect(x, y, rendered_w, rendered_h)
            drawing.setFont("Helvetica", 8)
            drawing.line(x, y - 13, x + rendered_w, y - 13)
            drawing.line(x, y - 17, x, y - 9)
            drawing.line(x + rendered_w, y - 17, x + rendered_w, y - 9)
            drawing.drawCentredString(x + rendered_w / 2, y - 25, f"{view_w:.2f} mm")
            drawing.saveState()
            drawing.translate(x - 15, y + rendered_h / 2)
            drawing.rotate(90)
            drawing.drawCentredString(0, 0, f"{view_h:.2f} mm")
            drawing.restoreState()

        drawing.setFont("Helvetica-Bold", 9)
        drawing.drawString(42, 128, "MATERIAL")
        drawing.setFont("Helvetica", 9)
        drawing.drawString(120, 128, requirements.material)
        drawing.setFont("Helvetica-Bold", 9)
        drawing.drawString(42, 110, "GENERAL NOTES")
        notes = [
            "1. DIMENSIONS ARE DERIVED FROM THE PARAMETRIC MODEL.",
            "2. REMOVE BURRS AND SHARP EDGES.",
            "3. TOLERANCES AND MANUFACTURING PROCESS REQUIRE ENGINEERING REVIEW.",
            f"4. {SAFETY_NOTICE.upper()}",
        ]
        drawing.setFont("Helvetica", 7)
        for index, note in enumerate(notes):
            drawing.drawString(42, 96 - index * 11, note[:145])
        drawing.save()
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _drawing_dxf(requirements: DesignRequirements, bbox: cq.BoundBox) -> bytes:
    document = ezdxf.new("R2013")
    space = document.modelspace()
    space.add_lwpolyline(
        [(0, 0), (bbox.xlen, 0), (bbox.xlen, bbox.ylen), (0, bbox.ylen)],
        close=True,
    )
    if requirements.hole_count and requirements.hole_diameter_mm:
        for x, y in _hole_positions(
            bbox.xlen, bbox.ylen, requirements.hole_count, requirements.hole_diameter_mm
        ):
            space.add_circle(
                (x + bbox.xlen / 2, y + bbox.ylen / 2),
                requirements.hole_diameter_mm / 2,
            )
    document.header["$INSUNITS"] = 4
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as handle:
        path = Path(handle.name)
    try:
        document.saveas(path)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def generate(request: GenerateRequest) -> GenerateResponse:
    shape, operations = build_shape(request.requirements)
    solid = shape.val()
    bbox = solid.BoundingBox()
    checks = [
        ValidationCheck(
            key="brep_valid",
            status="passed" if solid.isValid() else "failed",
            message="OpenCascade boundary representation validity check.",
            measured=solid.isValid(),
        ),
        ValidationCheck(
            key="positive_volume",
            status="passed" if solid.Volume() > 0 else "failed",
            message="Generated solid has positive volume.",
            measured=round(solid.Volume(), 6),
        ),
        ValidationCheck(
            key="finite_bounds",
            status="passed"
            if all(math.isfinite(value) and value > 0 for value in (bbox.xlen, bbox.ylen, bbox.zlen))
            else "failed",
            message="Bounding dimensions are finite and positive.",
            measured=f"{bbox.xlen:.3f} × {bbox.ylen:.3f} × {bbox.zlen:.3f} mm",
        ),
        ValidationCheck(
            key="structural_safety",
            status="not_evaluated",
            message="Structural capacity and safety require an approved analysis and professional review.",
        ),
    ]
    valid = all(check.status != "failed" for check in checks)
    preview = _mesh(shape, request.max_triangles)
    artifacts: list[ArtifactPayload] = []
    source = json.dumps(
        {
            "schema": "omniweb.parametric-design.v1",
            "requirements": request.requirements.model_dump(mode="json"),
            "operations": [operation.model_dump() for operation in operations],
        },
        indent=2,
    ).encode()
    artifacts.append(
        _artifact("source", "json", f"{request.design_id}-r{request.revision}.json", "application/json", source)
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for fmt, kind, media_type in (
            ("step", "cad_model", "model/step"),
            ("stl", "mesh", "model/stl"),
        ):
            path = root / f"{request.design_id}-r{request.revision}.{fmt}"
            cq.exporters.export(shape, str(path))
            data = path.read_bytes()
            artifacts.append(_artifact(kind, fmt, path.name, media_type, data))
    pdf = _drawing_pdf(request.requirements, bbox, request.revision)
    artifacts.append(
        _artifact(
            "drawing",
            "pdf",
            f"{request.design_id}-r{request.revision}.pdf",
            "application/pdf",
            pdf,
        )
    )
    if "dxf" in request.requirements.requested_outputs:
        dxf = _drawing_dxf(request.requirements, bbox)
        artifacts.append(
            _artifact(
                "dxf",
                "dxf",
                f"{request.design_id}-r{request.revision}.dxf",
                "application/dxf",
                dxf,
            )
        )
    return GenerateResponse(
        status="validated" if valid else "invalid",
        operations=operations,
        normalized_requirements=request.requirements,
        geometry={
            "valid": valid,
            "volume_mm3": round(solid.Volume(), 6),
            "surface_area_mm2": round(solid.Area(), 6),
            "bounds_mm": {
                "x": round(bbox.xlen, 6),
                "y": round(bbox.ylen, 6),
                "z": round(bbox.zlen, 6),
            },
            "center_of_mass_mm": [
                round(value, 6)
                for value in (
                    solid.Center().x,
                    solid.Center().y,
                    solid.Center().z,
                )
            ],
        },
        preview=preview,
        checks=checks,
        artifacts=artifacts,
    )
