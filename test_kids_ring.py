#!/usr/bin/env python3
"""The exit ring is a donut and the orange part grows clockwise from the top."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cairo  # noqa: E402

from kids_ring import paint_hold_ring  # noqa: E402

SIZE = 160


def paint(fraction):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1, 0.929, 0.835)
    ctx.paint()
    paint_hold_ring(ctx, SIZE, fraction)
    return surface


def pixel(surface, x, y):
    stride = surface.get_stride()
    data = surface.get_data()
    offset = y * stride + x * 4
    blue, green, red, alpha = data[offset : offset + 4]
    return red, green, blue, alpha


def kind(sample):
    _red, green, _blue, _alpha = sample
    if green < 110:
        return "fill"
    if 170 < green < 215:
        return "track"
    if green > 220:
        return "card"
    return "other"


def majority(surface, x, y, radius=2):
    counts = {}
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            name = kind(pixel(surface, x + dx, y + dy))
            counts[name] = counts.get(name, 0) + 1
    return max(counts, key=counts.get)


def point(theta_deg):
    theta = math.radians(theta_deg)
    radius = SIZE * 0.365
    x = SIZE / 2 + radius * math.sin(theta)
    y = SIZE / 2 - radius * math.cos(theta)
    return int(round(x)), int(round(y))


class HoldRingTests(unittest.TestCase):
    def test_the_center_stays_empty_and_the_fill_moves_clockwise(self):
        os.makedirs("/tmp/kids-ring", exist_ok=True)
        for fraction, name in ((0, "empty"), (0.25, "quarter"), (0.5, "half"), (1, "full")):
            paint(fraction).write_to_png(f"/tmp/kids-ring/{name}.png")

        empty = paint(0)
        quarter = paint(0.25)
        half = paint(0.5)
        full = paint(1)
        center = (SIZE // 2, SIZE // 2)
        self.assertEqual(majority(empty, *center), "card")
        self.assertEqual(majority(quarter, *center), "card")
        self.assertEqual(majority(full, *center), "card")
        self.assertEqual(majority(empty, *point(40)), "track")
        # 40 degrees clockwise from 12 o'clock is inside the first quarter.
        self.assertEqual(majority(quarter, *point(40)), "fill")
        self.assertEqual(majority(quarter, *point(180)), "track")
        self.assertEqual(majority(quarter, *point(270)), "track")
        self.assertEqual(majority(half, *point(40)), "fill")
        self.assertEqual(majority(half, *point(150)), "fill")
        self.assertEqual(majority(half, *point(270)), "track")
        self.assertEqual(majority(full, *point(40)), "fill")
        self.assertEqual(majority(full, *point(180)), "fill")
        self.assertEqual(majority(full, *point(270)), "fill")


if __name__ == "__main__":
    unittest.main()
