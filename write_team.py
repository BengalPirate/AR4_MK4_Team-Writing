"""Write "TEAM #2" on the whiteboard with a marker held at J6.

Sequence: Home -> above the first stroke -> each stroke (pen down, draw, pen up)
-> lift clear -> Home.

The start point (bottom-left corner of the text, marker tip touching the board)
is taught with jog_teach.py and stored in teach.json. Text runs toward the
robot's right (-Y) with letter tops pointing away from the robot (+X), so it
reads correctly from the robot's point of view.

Usage (close the stock AR4 app first):
  python write_team.py --preview        plot the path, no motion
  python write_team.py --air            full run with the pen 10 mm above the board
  python write_team.py                  write on the board
Options: --text, --height, --speed, --press, --hop, --air-offset, --port
"""
import argparse
import json
import os
import sys

from ar4link import AR4, AR4Error

HERE = os.path.dirname(os.path.abspath(__file__))
TEACH_FILE = os.path.join(HERE, "teach.json")

HOME_JOINTS = [0.0, 0.0, 0.0, 0.0, 45.0, 0.0]   # same as the stock app's Home.ar4
TEXT_DIR = (0.0, -1.0, 0.0)                     # baseline direction: robot's right
UP_DIR = (1.0, 0.0, 0.0)                        # letter "up": away from the robot

# Stroke font on a 12 x 20 cell (width x height). Each glyph is a list of
# polylines; each polyline is drawn with the pen down.
CELL_W, CELL_H = 12.0, 20.0
FONT = {
    "T": [[(0, 20), (12, 20)], [(6, 20), (6, 0)]],
    "E": [[(12, 20), (0, 20), (0, 0), (12, 0)], [(0, 10), (9, 10)]],
    "A": [[(0, 0), (6, 20), (12, 0)], [(2.4, 8), (9.6, 8)]],
    "M": [[(0, 0), (0, 20), (6, 8), (12, 20), (12, 0)]],
    "#": [[(4, 1), (4, 19)], [(8, 1), (8, 19)], [(1, 7), (11, 7)], [(1, 13), (11, 13)]],
    "2": [[(0, 16), (1.5, 19), (4, 20), (8, 20), (10.5, 19), (12, 16.5),
           (11, 13), (0, 0), (12, 0)]],
    "1": [[(3, 16), (6, 20), (6, 0)], [(3, 0), (9, 0)]],
    "3": [[(0, 20), (12, 20), (6, 11), (10, 10), (12, 6), (10, 1), (6, 0), (0, 2)]],
    "4": [[(9, 0), (9, 20), (0, 6), (12, 6)]],
    " ": [],
}
LETTER_GAP = 4.0   # in cell units, between glyphs
SPACE_W = 8.0      # in cell units, width of a space (plus its gaps)


def layout(text, height):
    """Return pen-down polylines in board coords (u along text, v up), mm."""
    scale = height / CELL_H
    strokes, cursor = [], 0.0
    for ch in text.upper():
        if ch not in FONT:
            sys.exit(f"No glyph for {ch!r}")
        if ch == " ":
            cursor += SPACE_W
            continue
        for line in FONT[ch]:
            strokes.append([((cursor + x) * scale, y * scale) for x, y in line])
        cursor += CELL_W + LETTER_GAP
    width = (cursor - LETTER_GAP) * scale
    return strokes, width


def to_robot(start, u, v, lift):
    """Board coords (mm) -> robot XYZ, `lift` mm above the board."""
    return (start["x"] + u * TEXT_DIR[0] + v * UP_DIR[0],
            start["y"] + u * TEXT_DIR[1] + v * UP_DIR[1],
            start["z"] + u * TEXT_DIR[2] + v * UP_DIR[2] + lift)


def preview(strokes, width, height, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 3))
    for line in strokes:
        ax.plot([p[0] for p in line], [p[1] for p in line], "-o", ms=2)
    ax.set_aspect("equal")
    ax.set_title(f"Path as seen by the robot: {width:.0f} x {height:.0f} mm")
    ax.set_xlabel("mm along text (robot's right)")
    ax.set_ylabel("mm up (away from robot)")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    print(f"Preview saved to {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", default="TEAM #2")
    ap.add_argument("--height", type=float, default=25.0, help="letter height, mm")
    ap.add_argument("--speed", type=int, default=10, help="speed, percent (1-25)")
    ap.add_argument("--press", type=float, default=0.5,
                    help="mm to push the pen below the taught touch height")
    ap.add_argument("--hop", type=float, default=8.0, help="pen-up height, mm")
    ap.add_argument("--air", action="store_true", help="run the whole path in the air")
    ap.add_argument("--air-offset", type=float, default=10.0)
    ap.add_argument("--preview", action="store_true", help="plot only, no motion")
    ap.add_argument("--port", help="serial port (default: auto-detect the Teensy)")
    args = ap.parse_args()

    with open(TEACH_FILE) as f:
        start = json.load(f)["start"]
    rot = (start["rz"], start["ry"], start["rx"])
    strokes, width = layout(args.text, args.height)
    print(f'"{args.text}": {len(strokes)} strokes, {width:.0f} mm wide '
          f"({width / 25.4:.1f} in), {args.height:.0f} mm tall")

    if args.preview:
        preview(strokes, width, args.height, os.path.join(HERE, "docs", "preview.png"))
        return

    down = (args.air_offset if args.air else 0.0) - args.press
    up = down + args.press + args.hop

    arm = AR4(args.port)
    try:
        p = arm.pose()
        if p.z < start["z"] + 30:
            print("Marker is near the board - lifting 30 mm straight up first ...")
            arm.move_linear(p.x, p.y, p.z + 30, *p.rot, speed_pct=args.speed)
        print("Moving to Home ...")
        arm.move_joints(HOME_JOINTS, args.speed)

        u0, v0 = strokes[0][0]
        print("Moving above the first stroke ...")
        arm.move_joint(*to_robot(start, u0, v0, up + 20), *rot, speed_pct=args.speed)

        for i, line in enumerate(strokes, 1):
            print(f"Stroke {i}/{len(strokes)}")
            u, v = line[0]
            arm.move_linear(*to_robot(start, u, v, up), *rot, speed_pct=args.speed)
            arm.move_linear(*to_robot(start, u, v, down), *rot, speed_pct=args.speed)
            for u, v in line[1:]:
                arm.move_linear(*to_robot(start, u, v, down), *rot, speed_pct=args.speed)
            arm.move_linear(*to_robot(start, u, v, up), *rot, speed_pct=args.speed)

        print("Done writing - lifting and returning Home ...")
        arm.move_linear(*to_robot(start, u, v, up + 30), *rot, speed_pct=args.speed)
        arm.move_joints(HOME_JOINTS, args.speed)
        print("Finished.")
    except AR4Error as e:
        print(f"\nSTOPPED: {e}")
        print("Check the arm. If the board stopped responding, replug the Teensy USB "
              "and recalibrate before running again.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted - the current move may still finish. Use the E-stop if needed.")
        sys.exit(1)
    finally:
        try:
            arm.sync_app_config()
        except AR4Error:
            pass
        arm.close()


if __name__ == "__main__":
    main()
