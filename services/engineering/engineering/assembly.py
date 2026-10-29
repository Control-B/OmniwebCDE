import json
import math
import tempfile
from pathlib import Path

import cadquery as cq

from .cad import _artifact, _mesh, build_shape
from .schemas import AssemblyGenerateRequest, AssemblyGenerateResponse, ValidationCheck

ASSEMBLY_NOTICE = (
    "Assembly geometry validation checks placement, solids, and exports only. It does "
    "not verify joints, fasteners, fit tolerances, loads, safety, or manufacturability."
)

DENSITY_KG_PER_MM3 = {
    "steel": 7.85e-6,
    "stainless steel": 8.0e-6,
    "aluminum": 2.70e-6,
    "aluminium": 2.70e-6,
    "brass": 8.50e-6,
    "copper": 8.96e-6,
    "abs": 1.04e-6,
    "polycarbonate": 1.20e-6,
    "nylon": 1.15e-6,
}


def _location(translation: list[float], rotation: list[float]) -> cq.Location:
    location = cq.Location(cq.Vector(*translation))
    for axis, angle in zip(
        (cq.Vector(1, 0, 0), cq.Vector(0, 1, 0), cq.Vector(0, 0, 1)),
        rotation,
        strict=True,
    ):
        if angle:
            location = location * cq.Location(cq.Vector(), axis, angle)
    return location


def generate_assembly(request: AssemblyGenerateRequest) -> AssemblyGenerateResponse:
    assembly = cq.Assembly(name=request.name)
    placed: list[tuple[str, cq.Shape]] = []
    bill_of_materials: list[dict] = []
    total_mass = 0.0

    for member_position, member in enumerate(request.members):
        shape, _ = build_shape(member.requirements)
        solid = shape.val()
        density = DENSITY_KG_PER_MM3.get(member.requirements.material.lower())
        mass_each = solid.Volume() * density if density else None
        if mass_each is not None:
            total_mass += mass_each * member.quantity
        bill_of_materials.append(
            {
                "member_id": member.member_id,
                "part_number": f"PART-{member.member_id[:8].upper()}",
                "name": member.name,
                "component_kind": member.requirements.component_kind.value,
                "material": member.requirements.material,
                "quantity": member.quantity,
                "volume_mm3_each": round(solid.Volume(), 6),
                "mass_kg_each": round(mass_each, 6) if mass_each is not None else None,
            }
        )
        for index in range(member.quantity):
            translation = [
                member.translation_mm[axis] + member.instance_spacing_mm[axis] * index
                for axis in range(3)
            ]
            location = _location(translation, member.rotation_deg)
            instance_name = f"{member.name}-{member_position + 1}-{index + 1}"
            assembly.add(solid, name=instance_name, loc=location)
            placed.append((instance_name, solid.located(location)))

    compound = cq.Compound.makeCompound([shape for _, shape in placed])
    workplane = cq.Workplane(obj=compound)
    bounds = compound.BoundingBox()
    invalid = [name for name, shape in placed if not shape.isValid()]
    collisions: list[dict] = []
    for left_index, (left_name, left_shape) in enumerate(placed):
        for right_name, right_shape in placed[left_index + 1 :]:
            overlap = left_shape.intersect(right_shape).Volume()
            if overlap > 0.001:
                collisions.append(
                    {
                        "members": [left_name, right_name],
                        "overlap_volume_mm3": round(overlap, 6),
                    }
                )

    checks = [
        ValidationCheck(
            key="member_solids_valid",
            status="failed" if invalid else "passed",
            message=(
                f"Invalid member solids: {', '.join(invalid)}."
                if invalid
                else "All placed member solids pass OpenCascade validity checks."
            ),
            measured=len(placed) - len(invalid),
        ),
        ValidationCheck(
            key="finite_assembly_bounds",
            status=(
                "passed"
                if all(
                    math.isfinite(value) and value > 0
                    for value in (bounds.xlen, bounds.ylen, bounds.zlen)
                )
                else "failed"
            ),
            message="Combined assembly bounds are finite and positive.",
            measured=f"{bounds.xlen:.3f} × {bounds.ylen:.3f} × {bounds.zlen:.3f} mm",
        ),
        ValidationCheck(
            key="interference_screen",
            status="warning" if collisions else "passed",
            message=(
                f"{len(collisions)} geometric overlap(s) require fit review."
                if collisions
                else "No volumetric interference detected between placed members."
            ),
            measured=len(collisions),
        ),
        ValidationCheck(
            key="joint_and_fastener_validation",
            status="not_evaluated",
            message=(
                "Joints, fasteners, mates, fit tolerances, and load transfer "
                "are not evaluated."
            ),
        ),
    ]
    valid = not invalid
    preview = _mesh(workplane, request.max_triangles)
    artifacts = []
    source = json.dumps(
        {
            "schema": "omniweb.parametric-assembly.v1",
            "name": request.name,
            "revision": request.revision,
            "members": [member.model_dump(mode="json") for member in request.members],
            "interferences": collisions,
        },
        indent=2,
    ).encode()
    artifacts.append(
        _artifact(
            "source",
            "json",
            f"{request.assembly_id}-r{request.revision}-assembly.json",
            "application/json",
            source,
        )
    )
    bom = json.dumps(
        {
            "schema": "omniweb.bill-of-materials.v1",
            "assembly": request.name,
            "revision": request.revision,
            "items": bill_of_materials,
        },
        indent=2,
    ).encode()
    artifacts.append(
        _artifact(
            "bill_of_materials",
            "json",
            f"{request.assembly_id}-r{request.revision}-bom.json",
            "application/json",
            bom,
        )
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        step_path = root / f"{request.assembly_id}-r{request.revision}.step"
        stl_path = root / f"{request.assembly_id}-r{request.revision}.stl"
        assembly.save(str(step_path), cq.exporters.ExportTypes.STEP)
        cq.exporters.export(workplane, str(stl_path))
        artifacts.extend(
            [
                _artifact(
                    "assembly_model",
                    "step",
                    step_path.name,
                    "model/step",
                    step_path.read_bytes(),
                ),
                _artifact(
                    "mesh",
                    "stl",
                    stl_path.name,
                    "model/stl",
                    stl_path.read_bytes(),
                ),
            ]
        )

    return AssemblyGenerateResponse(
        status="validated" if valid else "invalid",
        geometry={
            "valid": valid,
            "member_instances": len(placed),
            "unique_parts": len(request.members),
            "combined_volume_mm3": round(compound.Volume(), 6),
            "estimated_mass_kg": round(total_mass, 6),
            "bounds_mm": {
                "x": round(bounds.xlen, 6),
                "y": round(bounds.ylen, 6),
                "z": round(bounds.zlen, 6),
            },
            "interferences": collisions,
        },
        preview=preview,
        checks=checks,
        bill_of_materials=bill_of_materials,
        artifacts=artifacts,
        safety_notice=ASSEMBLY_NOTICE,
    )
