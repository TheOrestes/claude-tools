"""A minimal always-on-top Claude usage widget for Windows 11.

Drag with the left mouse button, double-click to collapse to one line,
right-click for the menu.
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import simpledialog

import usage

FROZEN = getattr(sys, "frozen", False)  # running as the PyInstaller exe
HERE = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent  # config/state live beside the exe
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"
FONT_DIR = (Path(sys._MEIPASS) if FROZEN else HERE) / "fonts"  # fonts are bundled inside the exe
FONT_FAMILY = "Space Grotesk"
FONT_FALLBACK = "Segoe UI"

DEFAULT_CONFIG = {
    "font_family": FONT_FAMILY,
    "budget_usd_per_window": 100.0,
    "auto_calibrate": True,
    "refresh_seconds": 15,
    "opacity": 0.92,
    "scale": 0,  # 0 = follow display DPI
    "zoom": 1.0,  # extra multiplier on top of scale, set from the right-click menu
    "theme": "Claude",
}

THEMES = {  # bg, track, text, muted, accent, hot -- same palettes as the system-info widget
    "Claude":   ("#262624", "#3d3d3a", "#faf9f5", "#9c9a92", "#d97757", "#e0533d"),
    "Midnight": ("#1a1b26", "#2f334d", "#c0caf5", "#7a88b8", "#7aa2f7", "#f7768e"),
    "Graphite": ("#1c1c1e", "#3a3a3c", "#f2f2f7", "#8e8e93", "#64d2ff", "#ff6961"),
    "Forest":   ("#1b231e", "#33443a", "#e8f1ea", "#8aa093", "#6fcf97", "#eb7b5c"),
    "Dracula":  ("#282a36", "#44475a", "#f8f8f2", "#8a8fb0", "#bd93f9", "#ff5555"),
    "Amber":    ("#1d1a14", "#3b342a", "#f5ecd9", "#a3987f", "#ffb454", "#ff6b4a"),
}
MODEL_COLORS = {  # opus follows the theme accent, see apply_theme
    "sonnet": "#5B8DB8",
    "haiku": "#63A375",
    "fable": "#9A7BC8",
    "mythos": "#9A7BC8",
    "other": "#6E6E78",
}


def mix(a: str, b: str, t: float) -> str:
    """Blend hex colour a toward b by t."""
    ca, cb = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def apply_theme(name: str) -> None:
    global BG, FG, DIM, LABEL, TRACK, SPARK, SPARK_NOW, LEVELS, CRITICAL
    BG, TRACK, FG, DIM, accent, CRITICAL = THEMES.get(name, THEMES["Claude"])
    LABEL, SPARK, SPARK_NOW = mix(DIM, BG, .45), mix(accent, BG, .45), accent
    LEVELS = ((0.60, accent), (0.85, "#E0A33E"))
    MODEL_COLORS["opus"] = accent


apply_theme("Claude")

W, H, H_COMPACT = 312, 122, 30  # W matches the system-info widget
HEADER = "C L A U D E   U S A G E"


def load_bundled_fonts() -> None:
    """Register the bundled fonts for this process only — nothing is installed."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        for ttf in sorted(FONT_DIR.glob("*.ttf")):
            ctypes.windll.gdi32.AddFontResourceExW(str(ttf), 0x10, 0)  # FR_PRIVATE
    except Exception:
        pass


def load_json(path: Path, default: dict) -> dict:
    try:
        return {**default, **json.loads(path.read_text("utf-8-sig"))}
    except (OSError, ValueError):
        return dict(default)


def save_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2), "utf-8")
    except OSError:
        pass


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_left(seconds: float) -> str:
    if seconds <= 0:
        return "idle"
    m = int(seconds // 60)
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def level_color(pct: float) -> str:
    for limit, color in LEVELS:
        if pct < limit:
            return color
    return CRITICAL


class Widget:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
        self.state = load_json(STATE_PATH, {"x": None, "y": None, "compact": False})
        self.reader = usage.Reader()
        self.compact = bool(self.state.get("compact"))
        self.snap: dict | None = None
        self._drag = (0, 0)
        self._job = None

        apply_theme(self.cfg["theme"])
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", float(self.cfg["opacity"]))
        root.configure(bg=BG)

        self.dpi = float(self.cfg["scale"]) or min(max(root.winfo_fpixels("1i") / 96.0, 1.0), 3.0)
        self.s = self.dpi * float(self.cfg["zoom"])
        wanted = str(self.cfg["font_family"])
        self.family = wanted if wanted in tkfont.families() else FONT_FALLBACK
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.build_menu()

        for seq, fn in (
            ("<Button-1>", self.press),
            ("<B1-Motion>", self.drag),
            ("<ButtonRelease-1>", self.drop),
            ("<Double-Button-1>", self.toggle_compact),
            ("<Button-3>", self.popup),
        ):
            self.canvas.bind(seq, fn)
        root.bind("<Escape>", lambda _e: self.quit())

        self.place()
        self.tick()

    def build_menu(self) -> None:
        style = dict(tearoff=0, bg=mix(BG, FG, .06), fg=FG, activebackground=SPARK_NOW,
                     activeforeground=BG, bd=0, selectcolor=FG)
        self.menu = tk.Menu(self.root, font=(self.family, 9), **style)
        self.menu.add_command(label="Refresh now", command=self.tick)
        self.menu.add_command(label="Set window budget...", command=self.set_budget)
        self.auto_var = tk.BooleanVar(value=bool(self.cfg["auto_calibrate"]))
        self.menu.add_checkbutton(label="Auto-calibrate budget", variable=self.auto_var,
                                  command=self.toggle_auto)
        for label, key, apply, opts in (
            ("Zoom", "zoom", self.set_zoom, [(f"{int(z * 100)}%", z) for z in (.75, 1.0, 1.25, 1.5, 1.75, 2.0)]),
            ("Opacity", "opacity", self.set_opacity, [(f"{p}%", p / 100) for p in (100, 90, 80, 70, 60, 50)]),
            ("Theme", "theme", self.set_theme, [(n, n) for n in THEMES]),
        ):
            sub = tk.Menu(self.menu, **style)
            var = tk.Variable(value=self.cfg[key])
            for text, val in opts:
                sub.add_radiobutton(label=text, variable=var, value=val, command=lambda f=apply, v=val: f(v))
            self.menu.add_cascade(label=label, menu=sub)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

    # ---- window ---------------------------------------------------------
    def place(self) -> None:
        w = int(W * self.s)
        h = int((H_COMPACT if self.compact else H) * self.s)
        x, y = self.state.get("x"), self.state.get("y")
        if x is None or y is None:
            x = self.root.winfo_screenwidth() - w - int(24 * self.s)
            y = int(48 * self.s)
        x = max(0, min(int(x), self.root.winfo_screenwidth() - w))
        y = max(0, min(int(y), self.root.winfo_screenheight() - h))
        self.state.update(x=x, y=y)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def press(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def drag(self, e):
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def drop(self, _e):
        self.state.update(x=self.root.winfo_x(), y=self.root.winfo_y())
        save_json(STATE_PATH, self.state)

    def toggle_compact(self, _e=None):
        self.compact = not self.compact
        self.state["compact"] = self.compact
        save_json(STATE_PATH, self.state)
        self.place()
        self.draw()

    def popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ---- menu actions ---------------------------------------------------
    def set_budget(self):
        helper = tk.Toplevel(self.root)  # dialogs need a normal parent window
        helper.withdraw()
        value = simpledialog.askfloat(
            "Window budget",
            "Usage budget per 5-hour window, in API-equivalent USD:",
            parent=helper,
            initialvalue=float(self.cfg["budget_usd_per_window"]),
            minvalue=0.1,
        )
        helper.destroy()
        if value:
            self.cfg["budget_usd_per_window"] = value
            save_json(CONFIG_PATH, self.cfg)
            self.tick()

    def toggle_auto(self):
        self.cfg["auto_calibrate"] = self.auto_var.get()
        save_json(CONFIG_PATH, self.cfg)
        self.tick()

    def set_opacity(self, value: float):
        self.cfg["opacity"] = value
        self.root.attributes("-alpha", value)
        save_json(CONFIG_PATH, self.cfg)

    def set_zoom(self, value: float):
        self.cfg["zoom"] = value
        self.s = self.dpi * value
        save_json(CONFIG_PATH, self.cfg)
        self.place()
        self.draw()

    def set_theme(self, name: str):
        self.cfg["theme"] = name
        apply_theme(name)
        save_json(CONFIG_PATH, self.cfg)
        self.root.configure(bg=BG)
        self.canvas.configure(bg=BG)
        self.build_menu()
        self.draw()

    def quit(self):
        if self._job:
            self.root.after_cancel(self._job)
        self.root.destroy()

    # ---- painting -------------------------------------------------------
    def tick(self):
        if self._job:
            self.root.after_cancel(self._job)
        try:
            self.snap = usage.snapshot(
                self.reader,
                float(self.cfg["budget_usd_per_window"]),
                bool(self.cfg["auto_calibrate"]),
            )
        except Exception:  # a widget must never die on one malformed transcript
            pass
        self.draw()
        self._job = self.root.after(max(3, int(self.cfg["refresh_seconds"])) * 1000, self.tick)

    def px(self, v: float) -> int:
        return int(round(v * self.s))

    def font(self, size: int, weight: str = "normal"):
        return (self.family, -self.px(size), weight)

    def rect(self, x0, y0, x1, y1, color):
        self.canvas.create_rectangle(self.px(x0), self.px(y0), self.px(x1), self.px(y1),
                                     fill=color, width=0)

    def bar(self, x0, y0, x1, y1, frac, color):
        self.rect(x0, y0, x1, y1, TRACK)
        if frac > 0:
            self.rect(x0, y0, x0 + (x1 - x0) * min(frac, 1.0), y1, color)

    def text(self, x, y, s, color=FG, size=10, weight="normal", anchor="w"):
        self.canvas.create_text(self.px(x), self.px(y), text=s, fill=color,
                                font=self.font(size, weight), anchor=anchor)

    def draw(self):
        self.canvas.delete("all")
        snap = self.snap
        if not snap:
            self.text(12, 15, "no usage data", DIM, 11)
            return

        pct = snap["pct"]
        color = level_color(pct)
        left = fmt_left(snap["remaining"])
        pad, right = 14, W - 14

        if self.compact:
            self.text(pad, 16, "C L A U D E", LABEL, 8)
            self.text(pad + 58, 15, f"{pct * 100:.0f}%", color, 13, "bold")
            self.bar(pad + 106, 12, right - 46, 18, pct, color)
            self.text(right, 15, left, DIM, 10, anchor="e")
            return

        # header, then the share of the current 5-hour window and when it resets
        self.text(pad, 15, HEADER, LABEL, 8)
        self.text(right, 15, f"resets {left}", DIM, 10, anchor="e")
        self.text(pad, 38, f"{pct * 100:.0f}%", color, 21, "bold")
        self.text(pad + 60, 41, fmt_tokens(snap["block_tokens"]), DIM, 10)

        # the filled part of the bar is itself split by model
        models = sorted(snap["block_models"].items(), key=lambda kv: -kv[1]["cost"])
        total = sum(m["cost"] for _, m in models)
        self.rect(pad, 54, right, 64, TRACK)
        filled = (right - pad) * pct
        x = pad
        for name, m in models:
            width = filled * (m["cost"] / total) if total else 0
            shade = MODEL_COLORS.get(name, MODEL_COLORS["other"])
            self.rect(x, 54, x + width, 64, CRITICAL if pct >= 0.85 else shade)
            x += width
        legend = "   ".join(f"{n} {fmt_tokens(m['tokens'])}" for n, m in models[:3])
        self.text(pad, 76, legend or "idle", DIM, 10)

        # today, hour by hour
        top, bottom = 86, 104
        hours = snap["hourly"]
        peak = max(hours) or 1.0
        slot = (right - pad) / 24
        for i, value in enumerate(hours):
            x0 = pad + i * slot
            x1 = x0 + slot - 1.5
            if value <= 0:
                self.rect(x0, bottom - 1, x1, bottom, TRACK)
            else:
                height = max((bottom - top) * (value / peak), 1.5)
                self.rect(x0, bottom - height, x1, bottom,
                          SPARK_NOW if i == snap["hour_now"] else SPARK)

        share = ""
        if snap["today_cost"] > 0:
            ranked = sorted(snap["today_models"].items(), key=lambda kv: -kv[1]["cost"])
            share = "  ".join(f"{n} {m['cost'] / snap['today_cost'] * 100:.0f}%"
                              for n, m in ranked[:2])
        self.text(pad, 114, f"today {fmt_tokens(snap['today_tokens'])}", DIM, 10)
        self.text(right, 114, share, DIM, 10, anchor="e")


def main():
    if sys.platform == "win32":
        try:  # crisp text on scaled displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    load_bundled_fonts()  # must happen before Tk enumerates font families
    root = tk.Tk()
    Widget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
