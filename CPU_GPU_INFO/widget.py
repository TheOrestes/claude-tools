import json, tkinter as tk, tkinter.font as tkf, urllib.request
import math
from functools import lru_cache
import psutil
from PIL import Image, ImageDraw, ImageTk

LHM = "http://localhost:8085/data.json"  # LibreHardwareMonitor > Options > Remote Web Server
import os
THEMES = {  # bg, track, text, muted, accent, hot
    "Claude":   ("#262624", "#3d3d3a", "#faf9f5", "#9c9a92", "#d97757", "#e0533d"),
    "Midnight": ("#1a1b26", "#2f334d", "#c0caf5", "#7a88b8", "#7aa2f7", "#f7768e"),
    "Graphite": ("#1c1c1e", "#3a3a3c", "#f2f2f7", "#8e8e93", "#64d2ff", "#ff6961"),
    "Forest":   ("#1b231e", "#33443a", "#e8f1ea", "#8aa093", "#6fcf97", "#eb7b5c"),
    "Dracula":  ("#282a36", "#44475a", "#f8f8f2", "#8a8fb0", "#bd93f9", "#ff5555"),
    "Amber":    ("#1d1a14", "#3b342a", "#f5ecd9", "#a3987f", "#ffb454", "#ff6b4a"),
}
CFG_PATH = os.path.expanduser("~/.syswidget.json")
CFG = dict(theme="Claude", zoom=1.0, alpha=0.95, x=40, y=40)
try: CFG.update(json.load(open(CFG_PATH)))
except Exception: pass
def save():
    try: json.dump(CFG, open(CFG_PATH, "w"))
    except OSError: pass
def col(i): return THEMES.get(CFG["theme"], THEMES["Claude"])[i]
def palette():
    global BG, TRACK, FG, MUTED, ORANGE, HOT
    BG, TRACK, FG, MUTED, ORANGE, HOT = (col(i) for i in range(6))
palette()
W, PAD = 312, 14
CPU_TEMP = ("CPU Package", "Core (Tctl/Tdie)", "Core Max")  # first match wins

def sensors():
    """[(hardware, sensor_id, name, type, value)] from LibreHardwareMonitor; [] if not running."""
    try:
        root = json.load(urllib.request.urlopen(LHM, timeout=0.5))
    except Exception:
        return []
    out = []
    def walk(n, hw):
        if n.get("HardwareId"): hw = n["Text"]
        if n.get("Type"):
            try: out.append((hw, n["SensorId"], n["Text"], n["Type"], float(n["Value"].split()[0].replace(",", "."))))
            except ValueError: pass
        for c in n["Children"]: walk(c, hw)
    walk(root, "")
    return out

def pick(s, prefix, typ, names):
    for name in names:
        for hw, sid, text, t, v in s:
            if sid.startswith(prefix) and t == typ and text == name: return v

def read():
    s = sensors()
    cpu = ("/intelcpu", "/amdcpu")
    d = dict(ok=bool(s), ssd=[])
    d["cpu_t"] = next((v for p in cpu if (v := pick(s, p, "Temperature", CPU_TEMP)) is not None), None)
    d["cpu_w"] = next((v for p in cpu if (v := pick(s, p, "Power", ("CPU Package",))) is not None), None)
    d["gpu_t"] = pick(s, "/gpu-nvidia", "Temperature", ("GPU Core",)) or pick(s, "/gpu-amd", "Temperature", ("GPU Core",))
    d["gpu_w"] = pick(s, "/gpu-nvidia", "Power", ("GPU Package",)) or pick(s, "/gpu-amd", "Power", ("GPU Package",))
    d["gpu_l"] = pick(s, "/gpu-nvidia", "Load", ("GPU Core",)) or pick(s, "/gpu-amd", "Load", ("GPU Core",))
    for hw, sid, text, t, v in s:
        if sid.startswith(("/nvme", "/hdd", "/ssd")) and t == "Temperature" and text in ("Composite Temperature", "Temperature"):
            d["ssd"].append((hw, v))
    return d

win = tk.Tk()
win.overrideredirect(True); win.attributes("-topmost", True, "-alpha", CFG["alpha"]); win.configure(bg=BG)
win.geometry(f'+{CFG["x"]}+{CFG["y"]}')
FONT = next((f for f in ("Space Grotesk", "Segoe UI") if f in tkf.families()), "Arial")
font = lambda sz, bold=False: (FONT, max(1, round(sz * CFG["zoom"])), "bold" if bold else "normal")
cv = tk.Canvas(win, bg=BG, highlightthickness=0); cv.pack()

state = dict(cpu_open=False, data=read())
hits = []  # (x0, y0, x1, y1, key)

def bar(x, y, w, pct, label="", right=""):
    cv.create_text(x, y + 6, text=label, fill=MUTED, anchor="w", font=font(8))
    bx = x + (22 if label else 0)
    cv.create_rectangle(bx, y + 1, x + w - (34 if right else 0), y + 11, fill=TRACK, width=0)
    cv.create_rectangle(bx, y + 1, bx + (x + w - (34 if right else 0) - bx) * min(pct, 100) / 100, y + 11, fill=ORANGE, width=0)
    if right: cv.create_text(x + w, y + 6, text=right, fill=FG, anchor="e", font=font(8))

@lru_cache(maxsize=256)
def arc_img(t, z, theme):  # Tk canvas arcs are aliased; draw 4x with PIL and downsample instead
    k, r, w = 4, 26 * z, 6 * z
    size = round(2 * (r + w) * k)
    c = size / 2
    im = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(im)
    R, W_ = r * k, w * k
    def arc(sweep, color):
        d.arc((c - R - W_ / 2, c - R - W_ / 2, c + R + W_ / 2, c + R + W_ / 2), 135, 135 + sweep, fill=color, width=round(W_))
        for a in (135, 135 + sweep):  # round caps
            x, y = c + R * math.cos(math.radians(a)), c + R * math.sin(math.radians(a))
            d.ellipse((x - W_ / 2, y - W_ / 2, x + W_ / 2, y + W_ / 2), fill=color)
    arc(270, TRACK)
    if t is not None:
        arc(270 * max(0.02, min(1, (t - 20) / 80)), HOT if t >= 85 else ORANGE)
    return ImageTk.PhotoImage(im.resize((size // k, size // k), Image.LANCZOS))

def gauge(cx, cy, r, t, label):
    cv.create_image(cx, cy, image=arc_img(None if t is None else round(t), CFG["zoom"], CFG["theme"]))
    cv.create_text(cx, cy, text="–" if t is None else f"{t:.0f}°", fill=FG, font=font(12, True))
    cv.create_text(cx, cy + r + 10, text=label, fill=MUTED, font=font(8))

def header(y, key, title, right, open_=None):
    arrow = "" if open_ is None else ("▾ " if open_ else "▸ ")
    cv.create_text(PAD, y, text=arrow + title, fill=ORANGE, anchor="w", font=font(9, True))
    cv.create_text(W - PAD, y, text=right, fill=FG, anchor="e", font=font(9))
    if key: hits.append((0, y - 10, W, y + 10, key))

def draw():
    d = state["data"]
    cv.delete("all"); hits.clear(); cv.configure(bg=BG); win.configure(bg=BG)
    cv.create_text(PAD, 16, text="SYSTEM", fill=FG, anchor="w", font=font(10, True))
    cv.create_text(W - PAD, 16, text="✕", fill=MUTED, anchor="e", font=font(10))
    hits.append((W - 40, 0, W, 30, "close"))
    y = 34
    g = [("CPU", d["cpu_t"]), ("GPU", d["gpu_t"])] + [(f"SSD{i}", v) for i, (hw, v) in enumerate(d["ssd"])]
    cell = (W - 2 * PAD) / 4
    for i, (lbl, t) in enumerate(g):
        gauge(PAD + cell * (i % 4 + .5), y + 32 + 78 * (i // 4), 26, t, lbl[:9])
    y += 78 * ((len(g) + 3) // 4) + 8

    load = psutil.cpu_percent(percpu=True)
    avg = sum(load) / len(load)
    header(y, "cpu", "CPU", f"{avg:.0f}%" + (f" · {d['cpu_w']:.0f} W" if d["cpu_w"] else ""), state["cpu_open"]); y += 16
    if state["cpu_open"]:
        half = (len(load) + 1) // 2
        cw = (W - 2 * PAD - 10) / 2
        for i, p in enumerate(load):
            bar(PAD + (cw + 10) * (i // half), y + 15 * (i % half), cw, p, f"{i}", f"{p:.0f}%")
        y += 15 * half + 4
    else:
        bar(PAD, y, W - 2 * PAD, avg); y += 18

    m = psutil.virtual_memory()
    header(y + 6, None, "RAM", f"{m.used / 2**30:.1f} / {m.total / 2**30:.1f} GB"); y += 22
    bar(PAD, y, W - 2 * PAD, m.percent); y += 18

    if d["gpu_w"] is not None or d["gpu_t"] is not None:
        header(y + 6, None, "GPU", " · ".join(f"{v:.0f}{u}" for v, u in ((d["gpu_t"], "°C"), (d["gpu_w"], " W")) if v is not None)); y += 22
        bar(PAD, y, W - 2 * PAD, d["gpu_l"] or 0); y += 18
    if not d["ok"]:
        cv.create_text(PAD, y + 12, text="start LibreHardwareMonitor (admin,\nweb server on) for temps", fill=MUTED, anchor="w", font=font(8)); y += 34
    z = CFG["zoom"]
    cv.scale("all", 0, 0, z, z)
    cv.config(width=W * z, height=(y + 10) * z)

def tick():
    state["data"] = read(); draw(); win.after(1000, tick)

def press(e): win._p = (e.x_root, e.y_root, win.winfo_x(), win.winfo_y())
def drag(e):
    px, py, wx, wy = win._p
    win.geometry(f"+{wx + e.x_root - px}+{wy + e.y_root - py}")
def release(e):
    px, py, *_ = win._p
    if abs(e.x_root - px) + abs(e.y_root - py) > 3:  # was a drag
        CFG.update(x=win.winfo_x(), y=win.winfo_y()); save(); return
    for x0, y0, x1, y1, k in hits:
        if x0 <= e.x / CFG["zoom"] <= x1 and y0 <= e.y / CFG["zoom"] <= y1:
            if k == "close": win.destroy(); return
            state["cpu_open"] = not state["cpu_open"]; draw()
cv.bind("<Button-1>", press); cv.bind("<B1-Motion>", drag); cv.bind("<ButtonRelease-1>", release)

def setcfg(k, v):
    CFG[k] = v; save()
    if k == "alpha": win.attributes("-alpha", v)
    if k == "theme": palette()
    draw()

menu = tk.Menu(win, tearoff=0)
for label, key, opts in (
    ("Zoom", "zoom", [(f"{int(z * 100)}%", z) for z in (.75, 1.0, 1.25, 1.5, 1.75, 2.0)]),
    ("Opacity", "alpha", [(f"{int(a * 100)}%", a) for a in (.5, .6, .7, .8, .9, 1.0)]),
    ("Theme", "theme", [(n, n) for n in THEMES]),
):
    sub = tk.Menu(menu, tearoff=0)
    var = tk.Variable(value=CFG[key])
    for text, val in opts:
        sub.add_radiobutton(label=text, variable=var, value=val, command=lambda k=key, v=val: setcfg(k, v))
    menu.add_cascade(label=label, menu=sub)
menu.add_separator(); menu.add_command(label="Close", command=win.destroy)
cv.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

tick(); win.mainloop()
