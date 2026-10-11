# claude-tools

Small Windows desktop widgets, MIT licensed.

- [claude-usage-widget](claude-usage-widget) - always-on-top Claude usage meter (standard library only).
- [CPU_GPU_INFO](CPU_GPU_INFO) - CPU/GPU system monitor widget.

## Install

Requires Windows and [Python 3](https://www.python.org/downloads/) (with tkinter, included by default).

```
git clone https://github.com/TheOrestes/claude-tools
cd claude-tools
```

**claude-usage-widget** (no dependencies):

```
cd claude-usage-widget
pythonw widget.py
```

**CPU_GPU_INFO**:

```
cd CPU_GPU_INFO
pip install -r requirements.txt
pythonw widget.py
```

To build a standalone exe, see each project's notes (`pip install pyinstaller`, then `python -m PyInstaller ...`).

## License

[MIT](LICENSE)
