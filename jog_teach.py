"""Jog the marker tip in small Cartesian steps and save the writing start point.

Run:  python jog_teach.py [PORT]      (PORT is optional; the Teensy is auto-detected)
Close the stock AR4 app first - only one program can use the serial port.

Axes are the robot base frame: +X away from the base, +Y to the robot's left,
+Z up. Tool orientation is held fixed while jogging.
"""
import json
import os
import tkinter as tk
from tkinter import messagebox

from ar4link import AR4, AR4Error

HERE = os.path.dirname(os.path.abspath(__file__))
TEACH_FILE = os.path.join(HERE, "teach.json")
STEPS_MM = (0.5, 1, 2, 5, 10, 25)


class JogApp:
    def __init__(self, root, port=None):
        self.root = root
        self.arm = AR4(port)
        root.title("AR4 Jog & Teach")

        self.pose_var = tk.StringVar()
        self.status_var = tk.StringVar(value=f"Connected: {os.path.basename(self.arm.port)}")
        self.step = tk.DoubleVar(value=5)
        self.speed = tk.IntVar(value=10)

        tk.Label(root, textvariable=self.pose_var, font=("monospace", 11),
                 justify="left").grid(row=0, column=0, columnspan=4, padx=8, pady=6, sticky="w")

        steps = tk.Frame(root)
        steps.grid(row=1, column=0, columnspan=4, sticky="w", padx=8)
        tk.Label(steps, text="Step (mm):").pack(side="left")
        for s in STEPS_MM:
            tk.Radiobutton(steps, text=str(s), variable=self.step, value=s).pack(side="left")
        tk.Label(steps, text="   Speed (%):").pack(side="left")
        tk.Spinbox(steps, from_=2, to=25, width=4, textvariable=self.speed).pack(side="left")

        self.buttons = []
        jog = tk.Frame(root)
        jog.grid(row=2, column=0, columnspan=4, pady=8)
        for col, (axis, neg, pos) in enumerate((("X", "X- (toward base)", "X+ (away)"),
                                                ("Y", "Y- (robot's right)", "Y+ (robot's left)"),
                                                ("Z", "Z- (down)", "Z+ (up)"))):
            for row, (label, sign) in enumerate(((pos, 1), (neg, -1))):
                b = tk.Button(jog, text=label, width=18,
                              command=lambda a=axis, s=sign: self.jog(a, s))
                b.grid(row=row, column=col, padx=4, pady=2)
                self.buttons.append(b)

        saves = tk.Frame(root)
        saves.grid(row=3, column=0, columnspan=4, pady=4)
        for name, text, color in (("start", "Save START (bottom-left of text)", "#2e7d32"),
                                  ("end", "Save END (bottom-right, ~100 mm along)", "#1565c0")):
            b = tk.Button(saves, text=text, bg=color, fg="white",
                          command=lambda n=name: self.save_point(n))
            b.pack(side="left", padx=4)
            self.buttons.append(b)

        goto = tk.Button(root, text="Go 20 mm above saved START", command=self.goto_start)
        goto.grid(row=5, column=0, columnspan=4, pady=(0, 6))
        self.buttons.append(goto)

        tk.Label(root, textvariable=self.status_var, fg="#555").grid(
            row=4, column=0, columnspan=4, padx=8, pady=6, sticky="w")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.refresh()

    def refresh(self):
        try:
            p = self.arm.pose()
        except AR4Error as e:
            self.pose_var.set("Position unavailable - board not responding.\n"
                              "Check the E-stop; if it persists, replug the Teensy USB\n"
                              "and recalibrate.")
            self.status_var.set(f"ERROR: {e}")
            return None
        self.pose_var.set(f"X {p.x:8.2f}   Y {p.y:8.2f}   Z {p.z:8.2f}  mm\n"
                          f"Rz {p.rz:7.2f}   Ry {p.ry:7.2f}   Rx {p.rx:7.2f}  deg\n"
                          + "  ".join(f"J{i + 1} {a:.1f}" for i, a in enumerate(p.joints)))
        return p

    def busy(self, on):
        for b in self.buttons:
            b.config(state="disabled" if on else "normal")
        self.root.config(cursor="watch" if on else "")
        self.root.update()

    def jog(self, axis, sign):
        self.busy(True)
        try:
            p = self.arm.pose()
            x, y, z = p.xyz
            d = sign * self.step.get()
            if axis == "X":
                x += d
            elif axis == "Y":
                y += d
            else:
                z += d
            self.status_var.set(f"Moving {axis} {d:+g} mm ...")
            self.root.update()
            self.arm.move_linear(x, y, z, *p.rot, speed_pct=int(self.speed.get()))
            self.status_var.set(f"Moved {axis} {d:+g} mm")
        except AR4Error as e:
            self.status_var.set(f"ERROR: {e}")
        finally:
            self.busy(False)
            self.refresh()

    def goto_start(self):
        if not os.path.exists(TEACH_FILE):
            messagebox.showerror("No START", "No START point saved yet.")
            return
        with open(TEACH_FILE) as f:
            s = json.load(f)["start"]
        if not messagebox.askokcancel(
                "Move arm?", "Move the marker to 20 mm above the saved START point?\n\n"
                "Hand on the E-stop. The arm moves joint-by-joint, not in a straight line."):
            return
        self.busy(True)
        try:
            self.status_var.set("Moving to 20 mm above START ...")
            self.root.update()
            self.arm.move_joint(s["x"], s["y"], s["z"] + 20, s["rz"], s["ry"], s["rx"],
                                speed_pct=int(self.speed.get()))
            self.status_var.set("Above START. Jog Z- in small steps to touch.")
        except AR4Error as e:
            self.status_var.set(f"ERROR: {e}")
        finally:
            self.busy(False)
            self.refresh()

    def save_point(self, name):
        p = self.refresh()
        if p is None:
            messagebox.showerror("Not saved", "Board is not responding - nothing saved.")
            return
        data = {}
        if os.path.exists(TEACH_FILE):
            with open(TEACH_FILE) as f:
                data = json.load(f)
        data[name] = p.as_dict()
        data["port"] = self.arm.port
        with open(TEACH_FILE, "w") as f:
            json.dump(data, f, indent=2)
        self.arm.sync_app_config()
        self.status_var.set(f"Saved {name.upper()} point to {TEACH_FILE}")
        messagebox.showinfo("Saved", f"{name.upper()} point saved:\n{p}")

    def quit(self):
        try:
            self.arm.sync_app_config()
        except AR4Error:
            pass  # board not responding; leave the app config as it is
        finally:
            self.arm.close()
            self.root.destroy()


if __name__ == "__main__":
    import sys
    root = tk.Tk()
    JogApp(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()
