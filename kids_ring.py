"""The exit-chord ring. It is a donut that fills clockwise over the hold."""

import math


def paint_hold_ring(ctx, size, fraction):
    """Draw a donut into a cairo context. The center stays undrawn.

    Fraction 0 is the empty ring. The orange sector grows clockwise from
    the top. The caller supplies the context and does not need to clear it.
    """
    if size <= 0:
        return
    fraction = 0.0 if fraction < 0 else 1.0 if fraction > 1 else fraction
    cx = size / 2
    cy = size / 2
    outer = size * 0.46
    inner = size * 0.27
    _annulus(ctx, cx, cy, outer, inner, 0, math.tau, 0.941, 0.761, 0.627, 1)
    if fraction <= 0:
        return
    start = -math.pi / 2
    _annulus(
        ctx,
        cx,
        cy,
        outer,
        inner,
        start,
        start + fraction * math.tau,
        0.761,
        0.255,
        0.047,
        1,
    )


def _annulus(ctx, cx, cy, outer, inner, start, end, red, green, blue, alpha):
    ctx.new_sub_path()
    ctx.set_source_rgba(red, green, blue, alpha)
    ctx.arc(cx, cy, outer, start, end)
    ctx.arc_negative(cx, cy, inner, end, start)
    ctx.close_path()
    ctx.fill()
