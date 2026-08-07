"""
Blender Python script — Building Construction + Light Ray Animation
=====================================================================

What it does:
  1. Clears the default scene.
  2. Builds N floors as stacked cuboids, each animated to "grow" upward
     from its own base (so the building rises floor-by-floor, bottom to top).
  3. Adds a thin antenna/spire on the roof once the last floor finishes.
  4. Emits a burst of glowing "light rays" (thin emissive cylinders) radiating
     outward from the antenna tip, staggered in time, plus a pulsing point light.
  5. Configures render + output settings (FFMPEG / MP4) so the animation can
     be rendered straight from the command line.

HOW TO USE
----------
Run this INSIDE Blender (Scripting tab -> Run Script) to build + preview it,
or run headless from a terminal (see the render command at the bottom of
this docstring and in the final section of the script).

Tested against Blender 4.x API (bpy). Minor API names differ slightly on
very old (2.8x) or very new versions — see comments where relevant.
"""

import bpy
import math
import os
from mathutils import Vector

# ---------------------------------------------------------------------------
# 0. CONFIG
# ---------------------------------------------------------------------------
NUM_FLOORS      = 8
FLOOR_HEIGHT    = 0.6
BUILDING_WIDTH  = 2.5
BUILDING_DEPTH  = 2.5

FRAMES_PER_FLOOR   = 15     # animation speed of construction
ANTENNA_FRAMES      = 15
RAY_COUNT           = 14
RAY_LENGTH           = 4.0
RAY_GROW_FRAMES     = 20
RAY_STAGGER          = 2     # frame offset between successive rays

FPS = 30

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "building_construction.mp4"
)  # absolute path next to this script — doesn't depend on the .blend being saved


# ---------------------------------------------------------------------------
# 1. CLEAN SCENE
# ---------------------------------------------------------------------------
def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block_collection in (bpy.data.meshes, bpy.data.materials,
                              bpy.data.lights, bpy.data.cameras):
        for block in list(block_collection):
            if block.users == 0:
                block_collection.remove(block)


# ---------------------------------------------------------------------------
# 2. MATERIAL HELPERS
# ---------------------------------------------------------------------------
def make_glass_material(name, color, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.15
    if "Transmission Weight" in bsdf.inputs:      # Blender 4.x naming
        bsdf.inputs["Transmission Weight"].default_value = 0.3
    elif "Transmission" in bsdf.inputs:            # older naming
        bsdf.inputs["Transmission"].default_value = 0.3

    if emission_strength > 0:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength

    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def make_emission_material(name, color, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = strength

    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# 3. GEOMETRY HELPERS
#    (mesh is shifted so the object's ORIGIN sits at the base, so scaling
#     the object grows it outward from that base rather than from its center)
# ---------------------------------------------------------------------------
def add_base_anchored_cube(name, size_xyz, base_location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name

    # shift mesh so local z spans 0..1 instead of -0.5..0.5
    for v in obj.data.vertices:
        v.co.z += 0.5

    obj.location = base_location
    obj.scale = size_xyz
    return obj


def add_base_anchored_cylinder(name, radius, base_location, direction=Vector((0, 0, 1))):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=1, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name

    for v in obj.data.vertices:
        v.co.z += 0.5   # local z spans 0..1

    obj.rotation_mode = 'QUATERNION'
    obj.rotation_quaternion = direction.to_track_quat('Z', 'Y')
    obj.location = base_location
    return obj


# ---------------------------------------------------------------------------
# 4. BUILD THE BUILDING (bottom -> top construction animation)
# ---------------------------------------------------------------------------
def build_floors():
    glass_mat = make_glass_material("BuildingGlass", (0.1, 0.35, 0.7))
    floors = []
    frame = 1

    for i in range(NUM_FLOORS):
        base_z = i * FLOOR_HEIGHT
        obj = add_base_anchored_cube(
            f"Floor_{i:02d}",
            (BUILDING_WIDTH, BUILDING_DEPTH, 0.001),   # start collapsed (near-zero height)
            (0, 0, base_z),
        )
        obj.data.materials.append(glass_mat)

        start_frame = frame
        end_frame = frame + FRAMES_PER_FLOOR

        # keyframe: collapsed at start_frame
        obj.scale = (BUILDING_WIDTH, BUILDING_DEPTH, 0.001)
        obj.keyframe_insert(data_path="scale", frame=start_frame)

        # keyframe: full height at end_frame
        obj.scale = (BUILDING_WIDTH, BUILDING_DEPTH, FLOOR_HEIGHT)
        obj.keyframe_insert(data_path="scale", frame=end_frame)

        floors.append(obj)
        frame = end_frame  # next floor starts as this one finishes (staggered rise)

    return floors, frame


# ---------------------------------------------------------------------------
# 5. ROOF ANTENNA
# ---------------------------------------------------------------------------
def build_antenna(top_z, start_frame):
    emit_mat = make_emission_material("AntennaGlow", (1.0, 1.0, 1.0), 2.0)
    obj = add_base_anchored_cylinder(
        "Antenna", radius=0.03, base_location=(0, 0, top_z), direction=Vector((0, 0, 1))
    )
    obj.data.materials.append(emit_mat)

    end_frame = start_frame + ANTENNA_FRAMES

    obj.scale = (1, 1, 0.001)
    obj.keyframe_insert(data_path="scale", frame=start_frame)
    obj.scale = (1, 1, 1.2)  # antenna height = 1.2
    obj.keyframe_insert(data_path="scale", frame=end_frame)

    return obj, end_frame


# ---------------------------------------------------------------------------
# 6. LIGHT RAYS RADIATING FROM THE ANTENNA TIP
# ---------------------------------------------------------------------------
def build_light_rays(apex_location, start_frame):
    ray_mat = make_emission_material("RayGlow", (1.0, 0.85, 0.3), 6.0)

    # a bright point light at the apex, animated from off -> bright
    light_data = bpy.data.lights.new("ApexLight", type='POINT')
    light_data.energy = 0.0
    light_data.color = (1.0, 0.85, 0.4)
    light_obj = bpy.data.objects.new("ApexLight", light_data)
    bpy.context.collection.objects.link(light_obj)
    light_obj.location = apex_location

    light_data.energy = 0.0
    light_obj.data.keyframe_insert(data_path="energy", frame=start_frame)
    light_data.energy = 400.0
    light_obj.data.keyframe_insert(data_path="energy", frame=start_frame + RAY_GROW_FRAMES)

    for i in range(RAY_COUNT):
        angle = (i / RAY_COUNT) * 2 * math.pi
        direction = Vector((math.cos(angle), math.sin(angle), 0.4)).normalized()

        ray = add_base_anchored_cylinder(
            f"Ray_{i:02d}", radius=0.015, base_location=apex_location, direction=direction
        )
        ray.data.materials.append(ray_mat)

        ray_start = start_frame + i * RAY_STAGGER
        ray_end = ray_start + RAY_GROW_FRAMES

        ray.scale = (1, 1, 0.001)
        ray.keyframe_insert(data_path="scale", frame=ray_start)
        ray.scale = (1, 1, RAY_LENGTH)
        ray.keyframe_insert(data_path="scale", frame=ray_end)

    last_ray_end = start_frame + (RAY_COUNT - 1) * RAY_STAGGER + RAY_GROW_FRAMES
    return last_ray_end


# ---------------------------------------------------------------------------
# 7. CAMERA, GROUND, WORLD LIGHTING
# ---------------------------------------------------------------------------
def build_environment():
    # ground
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "Ground"
    ground_mat = make_glass_material("GroundMat", (0.05, 0.05, 0.07))
    ground.data.materials.append(ground_mat)

    # sun for ambient scene lighting
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    sun = bpy.context.active_object
    sun.data.energy = 2.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))

    # ---- Camera: frame the WHOLE scene (building + antenna + rays) ----
    # Estimate the total extent of the animated content using the known
    # config constants, then back the camera off far enough (and angle it
    # at the vertical midpoint) so nothing gets cropped, regardless of the
    # exact NUM_FLOORS / RAY_LENGTH values used.
    building_top = NUM_FLOORS * FLOOR_HEIGHT
    scene_top = building_top + 1.2 + RAY_LENGTH        # antenna + ray reach
    scene_radius = max(BUILDING_WIDTH, BUILDING_DEPTH, RAY_LENGTH)

    cam_distance = (scene_top + scene_radius) * 1.6
    cam_location = Vector((cam_distance * 0.6, -cam_distance * 0.6, scene_top * 0.7))
    look_target = Vector((0, 0, scene_top * 0.35))

    bpy.ops.object.camera_add(location=cam_location)
    cam = bpy.context.active_object
    cam.data.lens = 28  # wider-angle lens so the full scene comfortably fits

    direction = (look_target - cam_location).normalized()
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = direction.to_track_quat('-Z', 'Y')

    bpy.context.scene.camera = cam

    return cam


# ---------------------------------------------------------------------------
# 8. RENDER / OUTPUT SETTINGS (MP4 via FFMPEG)
# ---------------------------------------------------------------------------
def configure_render(end_frame):
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = end_frame + 20  # small tail after rays finish
    scene.render.fps = FPS

    # Use Eevee for fast previews; switch to 'CYCLES' for higher quality
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in [
        e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items
    ] else 'BLENDER_EEVEE'

    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100

    scene.render.filepath = OUTPUT_PATH
    scene.render.image_settings.media_type = 'VIDEO'  # required before FFMPEG is a valid file_format (Blender 5.x)
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.ffmpeg.constant_rate_factor = 'HIGH'


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    # Set the default interpolation for all new keyframes up front, instead
    # of walking Action.fcurves after the fact — Blender 5.x's new layered
    # Action data model doesn't expose .fcurves directly the old way, so this
    # is the version-safe way to get snappy (non-overshooting) growth curves.
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'

    clear_scene()
    build_environment()

    floors, frame_after_floors = build_floors()
    top_z = NUM_FLOORS * FLOOR_HEIGHT
    antenna, frame_after_antenna = build_antenna(top_z, frame_after_floors)

    apex_location = Vector((0, 0, top_z + 1.2))
    frame_after_rays = build_light_rays(apex_location, frame_after_antenna)

    configure_render(frame_after_rays)

    print(f"Scene built. Animation spans frame 1 to {bpy.context.scene.frame_end}.")
    print(f"Render output will be written to: {OUTPUT_PATH}")


main()

# ---------------------------------------------------------------------------
# Render immediately when this script is run — enables fully headless
# command-line rendering:
#   blender --background --python building_construction_blender.py
# ---------------------------------------------------------------------------
bpy.ops.render.render(animation=True)
print(f"Render complete. Video saved to: {bpy.path.abspath(OUTPUT_PATH)}")
