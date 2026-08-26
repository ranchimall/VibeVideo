"""
Blender Python script — Split-Screen Video Format Setup
=========================================================

Creates a 1920x1080 output made of two independently-controlled panels:

    LEFT panel  : 608  x 1080   (requested 607.5 -> rounded, pixels must be whole)
    RIGHT panel : 1312 x 1080   (requested 1312.5 -> rounded)
    608 + 1312 = 1920  (exact full width, no gap/overlap)

HOW IT WORKS
------------
Three Scenes are created:
  - "Left"   : put whatever you want in the left panel here (own camera + objects)
  - "Right"  : put whatever you want in the right panel here (own camera + objects)
  - "SplitScreen_Master" : the scene you actually render. It has no 3D content
    of its own — its compositor reads the rendered output of "Left" and "Right"
    and places them side by side into the final 1920x1080 frame.

HOW TO ADD YOUR OWN CONTENT
----------------------------
In the Blender UI: use the Scene dropdown (top header, next to the scene
collection icon) to switch to "Left" or "Right", then add/animate objects,
cameras, lights normally — exactly like working in any other Blender scene.

From Python: link objects into bpy.data.scenes["Left"].collection (or
"Right"), e.g.:
    bpy.data.scenes["Left"].collection.objects.link(my_object)

RENDERING
---------
Always render "SplitScreen_Master" (this script sets it as the active scene).
Run headless from the command line:
    blender --background --python split_screen_setup.py
(the render call at the bottom is left commented out by default — see the
bottom of this script to enable full auto-render like in previous scripts)
"""

import bpy
import os

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
LEFT_WIDTH = 608     # requested 607.5 -> rounded to nearest whole pixel
RIGHT_WIDTH = 1312   # requested 1312.5 -> rounded to nearest whole pixel
HEIGHT = 1080
TOTAL_WIDTH = LEFT_WIDTH + RIGHT_WIDTH  # 1920

FPS = 30
FRAME_START = 1
FRAME_END = 250

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "split_screen_output.mp4"
)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def get_or_create_scene(name):
    if name in bpy.data.scenes:
        return bpy.data.scenes[name]
    return bpy.data.scenes.new(name)


def setup_content_scene(name, width, height):
    """Create/prepare a scene meant to hold one panel's content."""
    scene = get_or_create_scene(name)
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END

    # give it a default camera if it doesn't have one yet, so it renders
    # something sensible even before you've added your own setup
    if scene.camera is None:
        cam_data = bpy.data.cameras.new(f"{name}_Camera")
        cam_obj = bpy.data.objects.new(f"{name}_Camera", cam_data)
        scene.collection.objects.link(cam_obj)
        scene.camera = cam_obj
        cam_obj.location = (0, -8, 3)
        cam_obj.rotation_euler = (1.2, 0, 0)

    return scene


def setup_master_scene():
    """Create the compositing scene that combines Left + Right into 1920x1080."""
    master = get_or_create_scene("SplitScreen_Master")

    master.render.resolution_x = TOTAL_WIDTH
    master.render.resolution_y = HEIGHT
    master.render.resolution_percentage = 100
    master.render.fps = FPS
    master.frame_start = FRAME_START
    master.frame_end = FRAME_END

    master.use_nodes = True
    tree = bpy.data.node_groups.new("SplitScreenComposite", "CompositorNodeTree")
    master.compositing_node_group = tree
    tree.nodes.clear()

    # Blender 5.x compositor trees are node GROUPS: declare an output socket
    # via the interface, then feed it with a Group Output node (the old
    # dedicated "Composite" node was removed in 5.0).
    tree.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')

    # ---- Render Layers pulling from each content scene ----
    rl_left = tree.nodes.new("CompositorNodeRLayers")
    rl_left.scene = bpy.data.scenes["Left"]
    rl_left.location = (-700, 250)

    rl_right = tree.nodes.new("CompositorNodeRLayers")
    rl_right.scene = bpy.data.scenes["Right"]
    rl_right.location = (-700, -150)

    # ---- Translate each panel into its correct position within the
    #      1920-wide canvas. Canvas center = (0,0); panel buffers are
    #      centered by default, so we offset by the math below. ----
    left_center_x = -(TOTAL_WIDTH / 2) + (LEFT_WIDTH / 2)     # -656
    right_center_x = (TOTAL_WIDTH / 2) - (RIGHT_WIDTH / 2)    # +304

    translate_left = tree.nodes.new("CompositorNodeTranslate")
    translate_left.location = (-400, 250)
    translate_left.inputs["X"].default_value = left_center_x
    translate_left.inputs["Y"].default_value = 0

    translate_right = tree.nodes.new("CompositorNodeTranslate")
    translate_right.location = (-400, -150)
    translate_right.inputs["X"].default_value = right_center_x
    translate_right.inputs["Y"].default_value = 0

    # ---- Combine the two (non-overlapping, so Alpha Over is clean) ----
    alpha_over = tree.nodes.new("CompositorNodeAlphaOver")
    alpha_over.location = (-100, 50)

    # ---- Output (Group Output — the old "Composite" node was removed in 5.0) ----
    group_output = tree.nodes.new("NodeGroupOutput")
    group_output.location = (200, 50)

    links = tree.links
    links.new(rl_left.outputs["Image"], translate_left.inputs["Image"])
    links.new(rl_right.outputs["Image"], translate_right.inputs["Image"])
    links.new(translate_left.outputs["Image"], alpha_over.inputs[1])
    links.new(translate_right.outputs["Image"], alpha_over.inputs[2])
    links.new(alpha_over.outputs["Image"], group_output.inputs["Image"])

    # ---- Render/output settings (MP4 via FFMPEG) ----
    master.render.filepath = OUTPUT_PATH
    master.render.image_settings.media_type = 'VIDEO'
    master.render.image_settings.file_format = 'FFMPEG'
    master.render.ffmpeg.format = 'MPEG4'
    master.render.ffmpeg.codec = 'H264'
    master.render.ffmpeg.constant_rate_factor = 'HIGH'

    return master


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    setup_content_scene("Left", LEFT_WIDTH, HEIGHT)
    setup_content_scene("Right", RIGHT_WIDTH, HEIGHT)
    master = setup_master_scene()

    # make the master scene the active one so both the UI and a
    # subsequent `bpy.ops.render.render()` target it by default
    bpy.context.window.scene = master

    print("Split-screen setup complete.")
    print(f"  Left panel  scene: 'Left'  ({LEFT_WIDTH}x{HEIGHT})")
    print(f"  Right panel scene: 'Right' ({RIGHT_WIDTH}x{HEIGHT})")
    print(f"  Render 'SplitScreen_Master' for the combined {TOTAL_WIDTH}x{HEIGHT} output.")
    print(f"  Output will be written to: {OUTPUT_PATH}")


main()

# ---------------------------------------------------------------------------
# OPTIONAL: uncomment to render immediately when this script is run
# (for fully headless command-line rendering):
#   blender --background --python split_screen_setup.py
# ---------------------------------------------------------------------------
# bpy.ops.render.render(animation=True, scene="SplitScreen_Master")
# print(f"Render complete. Video saved to: {OUTPUT_PATH}")
