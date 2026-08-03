#!/usr/bin/env python3
"""Generate the control-panel operational flow diagram used by the manual."""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "images" / "11-program-operation-flow.png"

WIDTH = 2200
HEIGHT = 2850

BACKGROUND = "#ffffff"
TEXT = "#17324d"
MUTED = "#526d82"
BLUE = "#155a94"
DARK_BLUE = "#153e75"
LIGHT_BLUE = "#eaf4fb"
PALE_BLUE = "#f5f9fc"
GREEN = "#2f855a"
LIGHT_GREEN = "#eaf7ef"
AMBER = "#b7791f"
LIGHT_AMBER = "#fff8e6"
RED = "#c53030"
LIGHT_RED = "#fff1f1"
BORDER = "#8aafc9"


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        pathlib.Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        pathlib.Path(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


TITLE_FONT = load_font(54, bold=True)
GROUP_FONT = load_font(34, bold=True)
NODE_FONT = load_font(27, bold=True)
BODY_FONT = load_font(23)
SMALL_FONT = load_font(20)
LABEL_FONT = load_font(20, bold=True)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return "\n".join(lines)


def centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill: str = TEXT,
    spacing: int = 7,
) -> None:
    x1, y1, x2, y2 = box
    wrapped = wrap(draw, text, font, x2 - x1 - 36)
    bounds = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing, align="center")
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.multiline_text(
        ((x1 + x2 - text_width) / 2, (y1 + y2 - text_height) / 2 - bounds[1]),
        wrapped,
        font=font,
        fill=fill,
        spacing=spacing,
        align="center",
    )


def box(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    text: str,
    *,
    fill: str = LIGHT_BLUE,
    outline: str = BLUE,
    font: ImageFont.ImageFont = NODE_FONT,
    radius: int = 24,
    width: int = 4,
) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline, width=width)
    centered_text(draw, bounds, text, font)


def diamond(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    size: tuple[int, int],
    text: str,
    *,
    fill: str = LIGHT_AMBER,
    outline: str = AMBER,
) -> tuple[int, int, int, int]:
    cx, cy = center
    width, height = size
    points = [(cx, cy - height // 2), (cx + width // 2, cy), (cx, cy + height // 2), (cx - width // 2, cy)]
    draw.polygon(points, fill=fill, outline=outline)
    draw.line(points + [points[0]], fill=outline, width=4, joint="curve")
    bounds = (cx - width // 2, cy - height // 2, cx + width // 2, cy + height // 2)
    centered_text(draw, bounds, text, NODE_FONT)
    return bounds


def arrow_head(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str, width: int) -> None:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 20 + width
    spread = 0.55
    points = [
        end,
        (
            end[0] - length * math.cos(angle - spread),
            end[1] - length * math.sin(angle - spread),
        ),
        (
            end[0] - length * math.cos(angle + spread),
            end[1] - length * math.sin(angle + spread),
        ),
    ]
    draw.polygon(points, fill=color)


def arrow(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    *,
    color: str = BLUE,
    width: int = 6,
    label: str | None = None,
    dashed: bool = False,
) -> None:
    if dashed:
        for start, end in zip(points, points[1:], strict=False):
            dx, dy = end[0] - start[0], end[1] - start[1]
            distance = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / distance, dy / distance
            position = 0.0
            while position < distance:
                segment_end = min(distance, position + 22)
                draw.line(
                    [
                        (start[0] + ux * position, start[1] + uy * position),
                        (start[0] + ux * segment_end, start[1] + uy * segment_end),
                    ],
                    fill=color,
                    width=width,
                )
                position += 36
    else:
        draw.line(points, fill=color, width=width, joint="curve")
    arrow_head(draw, points[-2], points[-1], color, width)
    if label:
        longest_start, longest_end = max(
            zip(points, points[1:], strict=False),
            key=lambda pair: math.hypot(pair[1][0] - pair[0][0], pair[1][1] - pair[0][1]),
        )
        mx = (longest_start[0] + longest_end[0]) // 2
        my = (longest_start[1] + longest_end[1]) // 2
        label_box = draw.textbbox((0, 0), label, font=LABEL_FONT)
        padding = 8
        rect = (
            mx - (label_box[2] - label_box[0]) // 2 - padding,
            my - 25,
            mx + (label_box[2] - label_box[0]) // 2 + padding,
            my + 14,
        )
        draw.rounded_rectangle(rect, radius=8, fill=BACKGROUND)
        draw.text((rect[0] + padding, rect[1] + 4), label, font=LABEL_FONT, fill=color)


def group(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    title: str,
    *,
    fill: str = PALE_BLUE,
    outline: str = BORDER,
) -> None:
    draw.rounded_rectangle(bounds, radius=30, fill=fill, outline=outline, width=3)
    draw.text((bounds[0] + 24, bounds[1] + 18), title, font=GROUP_FONT, fill=DARK_BLUE)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    draw.text((WIDTH // 2, 42), "Program operation flow", font=TITLE_FONT, fill=DARK_BLUE, anchor="ma")
    draw.text(
        (WIDTH // 2, 105),
        "Major startup tasks, continuous loops, data storage, warnings, and user actions",
        font=BODY_FONT,
        fill=MUTED,
        anchor="ma",
    )

    # Startup
    group(draw, (95, 145, 2105, 610), "1. System startup")
    box(draw, (180, 245, 590, 390), "systemd starts\napplication services", fill=LIGHT_BLUE)
    box(draw, (690, 245, 1110, 390), "Load configuration and\npersisted settings", fill=LIGHT_BLUE)
    box(draw, (1210, 225, 1680, 410), "Initialize web API, SQLite,\nsyslog, SNMP, and\nnetwork agent connection", fill=LIGHT_BLUE)
    box(draw, (1780, 245, 2020, 390), "Start device\nworker", fill=LIGHT_GREEN, outline=GREEN)
    arrow(draw, [(590, 317), (690, 317)])
    arrow(draw, [(1110, 317), (1210, 317)])
    arrow(draw, [(1680, 317), (1780, 317)])

    profile = diamond(draw, (1100, 535), (520, 135), "Selected device profile?")
    arrow(draw, [(1900, 390), (1900, 535), (1360, 535)])

    # Acquisition loops
    group(draw, (95, 655, 1055, 1390), "2A. Amplifier acquisition loop", fill="#f4f9fd")
    box(draw, (180, 755, 510, 875), "Open selected\nserial port")
    box(draw, (630, 755, 970, 875), "Read one telemetry\nline")
    box(draw, (630, 970, 970, 1090), "Interpret and validate\nmeasurements")
    box(draw, (180, 970, 510, 1090), "Update current\ndevice values", fill=LIGHT_GREEN, outline=GREEN)
    box(draw, (345, 1190, 810, 1310), "On error: mark disconnected,\nwait, and reconnect", fill=LIGHT_RED, outline=RED, font=BODY_FONT)
    arrow(draw, [(510, 815), (630, 815)])
    arrow(draw, [(800, 875), (800, 970)])
    arrow(draw, [(630, 1030), (510, 1030)])
    arrow(draw, [(345, 1250), (145, 1250), (145, 815), (180, 815)], color=RED, label="retry", dashed=True)
    arrow(draw, [(350, 970), (350, 920), (500, 920), (500, 875)], color=BLUE, label="next line", dashed=True)

    group(draw, (1145, 655, 2105, 1390), "2B. Laser station acquisition loop", fill="#f4f9fd")
    box(draw, (1230, 755, 1560, 875), "Open and authenticate\nserial console")
    box(draw, (1680, 755, 2020, 875), "Poll station status\nand detail sections")
    box(draw, (1680, 970, 2020, 1090), "Normalize complete\nstation snapshot")
    box(draw, (1230, 970, 1560, 1090), "Update current\nstation values", fill=LIGHT_GREEN, outline=GREEN)
    box(draw, (1310, 1190, 1940, 1310), "Execute queued operator commands, wait for the poll interval,\nor reconnect after an error", fill=LIGHT_AMBER, outline=AMBER, font=BODY_FONT)
    arrow(draw, [(1560, 815), (1680, 815)])
    arrow(draw, [(1850, 875), (1850, 970)])
    arrow(draw, [(1680, 1030), (1560, 1030)])
    arrow(draw, [(1310, 1250), (1195, 1250), (1195, 815), (1230, 815)], color=BLUE, label="next poll", dashed=True)

    arrow(draw, [(840, profile[3]), (550, 655)], label="amplifier")
    arrow(draw, [(1360, profile[3]), (1650, 655)], label="laser station")

    # Common data processing
    group(draw, (95, 1445, 2105, 2025), "3. Processing shared by both device profiles", fill="#f7fbf8", outline="#9ac8ac")
    box(draw, (170, 1550, 580, 1685), "Current live state\nand last update", fill=LIGHT_GREEN, outline=GREEN)
    box(draw, (720, 1550, 1130, 1685), "Write measurements or\nsnapshots to SQLite", fill=LIGHT_GREEN, outline=GREEN)
    box(draw, (1270, 1550, 1680, 1685), "Evaluate warning\nconditions", fill=LIGHT_AMBER, outline=AMBER)
    warning = diamond(draw, (1900, 1618), (300, 135), "New or cleared\nwarning?")
    arrow(draw, [(510, 1390), (510, 1550)])
    arrow(draw, [(1560, 1390), (1560, 1550)])
    arrow(draw, [(580, 1618), (720, 1618)])
    arrow(draw, [(1130, 1618), (1270, 1618)])
    arrow(draw, [(1680, 1618), (1750, 1618)])

    box(draw, (170, 1810, 580, 1935), "Serve live data, history,\nwarnings, and settings by API", fill=LIGHT_BLUE)
    box(draw, (720, 1810, 1130, 1935), "Retain or prune history\naccording to configured limit", fill=LIGHT_BLUE)
    box(draw, (1270, 1810, 1680, 1935), "Update active warning\nstate in memory", fill=LIGHT_AMBER, outline=AMBER)
    box(draw, (1780, 1790, 2020, 1955), "Write syslog event\nand optional\nSNMP trap", fill=LIGHT_AMBER, outline=AMBER, font=BODY_FONT)
    arrow(draw, [(375, 1685), (375, 1810)])
    arrow(draw, [(925, 1685), (925, 1810)])
    arrow(draw, [(1900, warning[3]), (1900, 1790)], label="yes")
    arrow(draw, [(1750, 1618), (1700, 1618), (1700, 1872), (1680, 1872)], label="yes")

    # Browser and user loops
    group(draw, (95, 2080, 2105, 2780), "4. Browser refresh and user-action loops", fill="#f8f7fc", outline="#b4a7d6")
    box(draw, (165, 2190, 535, 2325), "Browser requests current\ndata from the API", fill="#f2effa", outline="#6b46a1")
    box(draw, (165, 2460, 535, 2595), "Render live view, charts,\nwarnings, and diagnostics", fill="#f2effa", outline="#6b46a1")
    arrow(draw, [(350, 2325), (350, 2460)], color="#6b46a1")
    arrow(draw, [(165, 2528), (120, 2528), (120, 2258), (165, 2258)], color="#6b46a1", label="periodic refresh", dashed=True)
    arrow(draw, [(375, 2190), (375, 1935)], color="#6b46a1")

    box(draw, (680, 2190, 1030, 2325), "User submits a control\nor settings change", fill="#f2effa", outline="#6b46a1")
    box(draw, (680, 2460, 1030, 2595), "Check login role, validate\nvalue, and record audit event", fill=LIGHT_AMBER, outline=AMBER)
    arrow(draw, [(855, 2325), (855, 2460)], color="#6b46a1")

    diamond(draw, (1310, 2528), (390, 160), "Action type?")
    arrow(draw, [(1030, 2528), (1115, 2528)], color="#6b46a1")

    box(draw, (1575, 2130, 2035, 2250), "Device command -> serial worker\nand next status confirmation", fill=LIGHT_BLUE, font=BODY_FONT)
    box(draw, (1575, 2350, 2035, 2470), "Application setting ->\npersisted_state.json", fill=LIGHT_GREEN, outline=GREEN, font=BODY_FONT)
    box(draw, (1575, 2570, 2035, 2700), "Network setting -> host agent\ncheckpoint -> confirm or rollback", fill=LIGHT_RED, outline=RED, font=BODY_FONT)
    arrow(draw, [(1410, 2455), (1500, 2190), (1575, 2190)], label="device")
    arrow(draw, [(1505, 2528), (1538, 2410), (1575, 2410)], label="setting")
    arrow(draw, [(1410, 2600), (1500, 2635), (1575, 2635)], label="network")
    arrow(
        draw,
        [(1805, 2130), (2070, 2130), (2070, 1250), (1940, 1250)],
        color=BLUE,
        dashed=True,
    )

    draw.line((115, 2815, 205, 2815), fill=BLUE, width=6)
    draw.text((225, 2799), "normal flow", font=SMALL_FONT, fill=MUTED)
    for x in range(420, 510, 30):
        draw.line((x, 2815, min(x + 16, 510), 2815), fill=BLUE, width=6)
    draw.text((530, 2799), "continuous or retry loop", font=SMALL_FONT, fill=MUTED)
    draw.text((2050, 2799), "Generated from tools/generate_program_flow_diagram.py", font=SMALL_FONT, fill=MUTED, anchor="ra")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, optimize=True)
    print(f"Generated {OUTPUT} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()
