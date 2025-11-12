"""
Utilities for fetching and rendering a GitHub contribution heatmap.

The remote SVG is converted into a 7xN matrix (Sunday-first), then
rendered using ANSI background colors (if stdout is a TTY) or ASCII
fall-back characters otherwise.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from typing import Dict, List, Sequence


_LEVEL_COLORS = [
    (235, 237, 240),
    (155, 233, 168),
    (64, 196, 99),
    (48, 161, 78),
    (33, 110, 57),
]
_LEVEL_ASCII = [" ", ".", ":", "=", "#"]
_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


class HeatmapError(RuntimeError):
    """Custom error for clarity in the CLI output."""


def show_remote_heatmap(username: str, weeks: int = 30) -> List[List[int]]:
    """
    Fetch and render the latest GitHub contribution heatmap for a user.

    Returns the parsed 7xN matrix (or an empty list on failures).
    """
    if not username:
        print("[heatmap] github_username 未配置，跳过抓取。")
        return []

    weeks = max(1, int(weeks or 1))
    try:
        matrix = _build_matrix(username, weeks)
    except HeatmapError as exc:
        print(f"[heatmap] {exc}")
        return []
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[heatmap] 抓取热力图失败：{exc}")
        return []

    _render_matrix(matrix, username)
    return matrix


def _build_matrix(username: str, weeks: int) -> List[List[int]]:
    level_by_date = _fetch_levels(username)
    if not level_by_date:
        raise HeatmapError("未解析到任何贡献数据。")

    latest_date = max(level_by_date)
    last_sunday = latest_date - _dt.timedelta(days=_days_since_sunday(latest_date))
    start_sunday = last_sunday - _dt.timedelta(weeks=weeks - 1)

    matrix = [[0 for _ in range(weeks)] for _ in range(7)]
    for col in range(weeks):
        week_start = start_sunday + _dt.timedelta(weeks=col)
        for row in range(7):
            day = week_start + _dt.timedelta(days=row)
            matrix[row][col] = int(level_by_date.get(day, 0))
    return matrix


def _fetch_levels(username: str) -> Dict[_dt.date, int]:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - import guard
        raise HeatmapError("缺少 requests，请先运行 pip install requests。") from exc

    url = f"https://github.com/users/{username}/contributions"
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "GitHub Heatmap Streaker TUI",
                "Accept": "text/html",
            },
        )
    except requests.RequestException as exc:  # pragma: no cover - network guard
        raise HeatmapError(f"网络请求失败：{exc}") from exc

    if resp.status_code != 200:
        raise HeatmapError(f"GitHub 返回状态码 {resp.status_code}")

    return _parse_levels(resp.text)


def _render_matrix(matrix: Sequence[Sequence[int]], username: str) -> None:
    if not matrix:
        print("[heatmap] 无热力图数据可展示。")
        return

    print(f"\n[heatmap] {username} 最近 {len(matrix[0])} 周贡献热力图：")
    colored = sys.stdout.isatty()
    for row_idx, row in enumerate(matrix):
        row_buf = []
        for level in row:
            level = max(0, min(4, int(level)))
            if colored:
                r, g, b = _LEVEL_COLORS[level]
                row_buf.append(f"\033[48;2;{r};{g};{b}m  \033[0m")
            else:
                row_buf.append(_LEVEL_ASCII[level])
        print(f"{_DAY_NAMES[row_idx]:>3} " + "".join(row_buf))
    print()


def _days_since_sunday(day: _dt.date) -> int:
    # Monday == 0, Sunday == 6 -> convert to Sunday-first shift
    return (day.weekday() + 1) % 7


def _parse_levels(html: str) -> Dict[_dt.date, int]:
    patterns = [
        re.compile(
            r'<rect[^>]*data-date="([\d-]+)"[^>]*data-level="(\d+)"[^>]*>',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'<td[^>]*data-date="([\d-]+)"[^>]*data-level="(\d+)"[^>]*>',
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    data: Dict[_dt.date, int] = {}
    for pattern in patterns:
        matches = pattern.findall(html)
        if not matches:
            continue
        for date_str, level_str in matches:
            try:
                day = _dt.date.fromisoformat(date_str)
                level = max(0, min(4, int(level_str)))
            except ValueError:
                continue
            data[day] = level
        if data:
            break

    return data


__all__ = ["show_remote_heatmap", "HeatmapError"]
