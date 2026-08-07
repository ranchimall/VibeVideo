"""
3D Building Construction + Light Ray Animation (Manim Community)

Run with:
    pip install manim
    manim -pql building_construction.py BuildingConstruction

Use -pqh instead of -pql for higher quality rendering.
"""

from manim import *
import numpy as np


class BuildingConstruction(ThreeDScene):
    def construct(self):
        # ---- Camera setup ----
        self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES, distance=10)
        self.camera.background_color = "#0b0b1a"

        # ---- Building parameters ----
        num_floors = 8
        floor_height = 0.6
        building_width = 2.5
        building_depth = 2.5

        # ---- Build floor stack (bottom to top) ----
        floors = VGroup()
        for i in range(num_floors):
            floor = Cube(
                side_length=1,
                fill_opacity=0.85,
                fill_color=BLUE_E,
                stroke_color=BLUE_A,
                stroke_width=1,
            )
            floor.stretch_to_fit_width(building_width)
            floor.stretch_to_fit_depth(building_depth)
            floor.stretch_to_fit_height(floor_height)
            floor.shift(UP * (floor_height * i + floor_height / 2))

            # subtle color gradient from base to top
            shade = interpolate_color(BLUE_E, BLUE_B, i / num_floors)
            floor.set_fill(shade, opacity=0.85)
            floors.add(floor)

        # Ground plane for context
        ground = Square(side_length=6, fill_color=GREY_E, fill_opacity=0.6, stroke_opacity=0)
        ground.rotate(PI / 2, axis=RIGHT)
        ground.shift(DOWN * 0.001)
        self.add(ground)

        # slow camera rotation for a 3D "alive" feel
        self.begin_ambient_camera_rotation(rate=0.15)

        # ---- Animate floors rising one by one, bottom -> top ----
        for floor in floors:
            self.play(GrowFromEdge(floor, DOWN), run_time=0.5)

        self.wait(0.5)

        # ---- Antenna / roof spire ----
        antenna = Line(
            start=floors[-1].get_top(),
            end=floors[-1].get_top() + UP * 1.2,
            color=WHITE,
            stroke_width=4,
        )
        self.play(Create(antenna), run_time=0.6)
        self.wait(0.3)

        # ---- Light rays emanating from the top ----
        light_source = antenna.get_end()

        rays = VGroup()
        num_rays = 14
        for i in range(num_rays):
            angle = i * TAU / num_rays
            direction = np.array([np.cos(angle), np.sin(angle), 0.35])
            direction = direction / np.linalg.norm(direction)
            ray = Line(
                start=light_source,
                end=light_source + direction * 4,
                color=YELLOW,
                stroke_width=2,
                stroke_opacity=0.8,
            )
            rays.add(ray)

        glow = Dot3D(point=light_source, radius=0.15, color=YELLOW)

        self.play(FadeIn(glow, scale=0.5))
        self.play(
            LaggedStart(*[Create(ray) for ray in rays], lag_ratio=0.05),
            run_time=1.5,
        )

        # pulse the light source for emphasis
        self.play(glow.animate.scale(1.8).set_opacity(0.3), run_time=0.8)
        self.play(glow.animate.scale(1 / 1.8).set_opacity(1), run_time=0.8)

        self.wait(2)