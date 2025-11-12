"""
Simple curses-based grid editor for designing GitHub contribution patterns.
"""

from __future__ import annotations

import copy
import sys
from typing import Dict, List, Tuple

try:  # pragma: no cover - platform dependent
    import curses
except ImportError:  # pragma: no cover - e.g. Windows without windows-curses
    curses = None  # type: ignore[assignment]


DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
CTRL_S = 19  # ASCII XOFF
HELP_TEXT = (
    "Arrows/WASD 移动 · 0-9 设值 · 空格 0/5 · C 循环 0→3→6→9 · "
    "Ctrl+S 保存 · Q 放弃"
)


def run_tui(initial_pattern: List[List[int]]) -> Tuple[List[List[int]], bool]:
    """
    Launch the curses TUI for editing the pattern.

    Returns (pattern, should_save).
    """
    pattern = copy.deepcopy(initial_pattern)
    if not pattern or len(pattern) != 7:
        raise ValueError("Pattern 必须包含 7 行（周日→周六）。")
    cols = len(pattern[0])
    if cols == 0:
        raise ValueError("Pattern 至少需要 1 列。")
    if curses is None:
        print("[tui] 当前 Python 缺少 curses，请先安装 windows-curses 或使用支持的终端。")
        return pattern, False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("[tui] 终端不支持交互，取消编辑。")
        return pattern, False

    state = {"save": False}

    def _wrapped(stdscr: "curses._CursesWindow") -> None:
        _run_editor(stdscr, pattern, state)

    try:
        curses.wrapper(_wrapped)
    except curses.error as exc:
        print(f"[tui] curses 运行失败：{exc}")
        return pattern, False

    return pattern, bool(state["save"])


def _run_editor(stdscr: "curses._CursesWindow", pattern: List[List[int]], state) -> None:
    rows, cols = len(pattern), len(pattern[0])
    cursor_row, cursor_col = 0, 0
    message = "编辑完成后按 Ctrl+S 保存。"
    color_palette = _setup_color_pairs()

    try:
        curses.curs_set(0)
    except curses.error:  # pragma: no cover - not all terminals support it
        pass

    stdscr.keypad(True)

    while True:
        _draw(stdscr, pattern, cursor_row, cursor_col, message, color_palette)
        ch = stdscr.getch()

        if ch in (ord("q"), ord("Q")):
            state["save"] = False
            message = "已放弃修改。"
            break
        if ch == CTRL_S:
            state["save"] = True
            message = "保存成功。"
            break

        if ch in (curses.KEY_UP, ord("w"), ord("W")):
            cursor_row = max(0, cursor_row - 1)
            continue
        if ch in (curses.KEY_DOWN, ord("s")):
            cursor_row = min(rows - 1, cursor_row + 1)
            continue
        if ch in (curses.KEY_LEFT, ord("a"), ord("A")):
            cursor_col = max(0, cursor_col - 1)
            continue
        if ch in (curses.KEY_RIGHT, ord("d"), ord("D")):
            cursor_col = min(cols - 1, cursor_col + 1)
            continue
        if ord("0") <= ch <= ord("9"):
            pattern[cursor_row][cursor_col] = ch - ord("0")
            continue
        if ch == ord(" "):
            pattern[cursor_row][cursor_col] = 5 if pattern[cursor_row][cursor_col] == 0 else 0
            continue
        if ch in (ord("c"), ord("C")):
            pattern[cursor_row][cursor_col] = _cycle(pattern[cursor_row][cursor_col])
            continue

        message = f"未知按键：{ch}"


def _cycle(current: int) -> int:
    seq = [0, 3, 6, 9]
    if current not in seq:
        return seq[0]
    idx = (seq.index(current) + 1) % len(seq)
    return seq[idx]


def _draw(
    stdscr: "curses._CursesWindow",
    pattern: List[List[int]],
    cursor_row: int,
    cursor_col: int,
    message: str,
    color_palette: Dict[int, int],
) -> None:
    stdscr.erase()
    rows, cols = len(pattern), len(pattern[0])
    max_y, _max_x = stdscr.getmaxyx()

    stdscr.addstr(0, 0, "GitHub Heatmap Streaker TUI")
    stdscr.addstr(1, 0, HELP_TEXT)

    header = "    " + "".join(str(col % 10) for col in range(cols))
    stdscr.addstr(3, 0, header)

    for r in range(rows):
        line_y = 4 + r
        if line_y >= max_y - 2:
            break
        stdscr.addstr(line_y, 0, f"{DAY_NAMES[r]:>3} ")
        for c in range(cols):
            ch = str(pattern[r][c] % 10)
            attr = _color_attr_for_value(pattern[r][c], color_palette)
            if r == cursor_row and c == cursor_col:
                attr |= curses.A_BOLD | curses.A_UNDERLINE
            try:
                stdscr.addch(line_y, 4 + c, ch, attr)
            except curses.error:
                # Terminal not wide enough; stop drawing remaining cells.
                break

    info_line = 5 + rows
    if info_line < max_y:
        stdscr.addstr(
            info_line,
            0,
            f"光标: {DAY_NAMES[cursor_row]} 第 {cursor_col + 1} 列 · 当前值: {pattern[cursor_row][cursor_col]}   ",
        )

    if max_y - 1 > info_line:
        stdscr.addstr(max_y - 2, 0, message[: _max_x - 1])

    stdscr.refresh()


def _setup_color_pairs() -> Dict[int, int]:
    palette: Dict[int, int] = {}
    try:
        curses.start_color()
    except curses.error:
        return palette
    if not curses.has_colors():
        return palette

    try:
        curses.use_default_colors()
    except curses.error:
        pass

    github_rgb = [
        (235, 237, 240),  # level 0
        (155, 233, 168),
        (64, 196, 99),
        (48, 161, 78),
        (33, 110, 57),
    ]
    fallback_bg = [
        curses.COLOR_WHITE,
        curses.COLOR_GREEN,
        curses.COLOR_CYAN,
        curses.COLOR_BLUE,
        curses.COLOR_MAGENTA,
    ]
    fallback_fg = [curses.COLOR_BLACK, curses.COLOR_BLACK, curses.COLOR_BLACK, curses.COLOR_WHITE, curses.COLOR_WHITE]
    can_custom = curses.can_change_color() and curses.COLORS >= 16 + len(github_rgb)

    for level, rgb in enumerate(github_rgb):
        pair_id = level + 1
        fg_color = fallback_fg[level]
        bg_color = fallback_bg[level]
        if can_custom:
            color_number = 16 + level
            try:
                r = rgb[0] * 1000 // 255
                g = rgb[1] * 1000 // 255
                b = rgb[2] * 1000 // 255
                curses.init_color(color_number, r, g, b)
                bg_color = color_number
            except curses.error:
                pass

        try:
            curses.init_pair(pair_id, fg_color, bg_color)
            palette[level] = curses.color_pair(pair_id)
        except curses.error:
            palette[level] = 0

    return palette


def _value_to_level(value: int) -> int:
    val = max(0, value)
    if val == 0:
        return 0
    if val <= 2:
        return 1
    if val <= 5:
        return 2
    if val <= 8:
        return 3
    return 4


def _color_attr_for_value(value: int, palette: Dict[int, int]) -> int:
    if not palette:
        return curses.A_NORMAL
    level = _value_to_level(value)
    return palette.get(level, curses.A_NORMAL)


__all__ = ["run_tui"]
