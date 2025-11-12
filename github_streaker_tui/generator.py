"""
File generation helpers for GitHub Heatmap Streaker.

save_all(pattern, cfg) materializes the runtime artifacts inside the target
repository.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import List


def save_all(pattern: List[List[int]] | None, cfg: dict) -> None:
    repo_path = Path(cfg["repo_path"]).expanduser().resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"目标仓库不存在：{repo_path}")

    mode = cfg.get("mode", "pattern")
    weeks = max(1, int(cfg.get("weeks", 52)))
    if mode == "pattern":
        if pattern is None:
            raise ValueError("Pattern 模式需要图案矩阵。")
        if len(pattern) != 7 or any(len(row) != len(pattern[0]) for row in pattern):
            raise ValueError("Pattern 必须为 7×N 矩阵。")
    else:
        daily_count = int(cfg.get("daily_commit_count", 0))
        if daily_count <= 0:
            raise ValueError("每日定量模式需要正数 daily_commit_count。")
        pattern = _build_daily_pattern(daily_count, weeks)

    start_date = _calculate_start_date(bool(cfg.get("start_from_next_sunday")), mode)

    _write_pattern_json(repo_path, pattern, start_date, mode, int(cfg.get("daily_commit_count", 0)))
    _write_workflow(repo_path, cfg)
    _write_painter_script(repo_path)
    _write_agreement(repo_path)

    print(f"[generator] 已生成 heatmap 相关文件于：{repo_path}")


def _calculate_start_date(start_from_next_sunday: bool, mode: str) -> _dt.date:
    today = _dt.date.today()
    if mode != "pattern":
        return today
    if not start_from_next_sunday:
        return today
    delta = (6 - today.weekday()) % 7  # Next Sunday, inclusive
    return today + _dt.timedelta(days=delta)


def _write_pattern_json(
    repo_path: Path,
    pattern: List[List[int]],
    start_date: _dt.date,
    mode: str,
    daily_commit_count: int,
) -> None:
    data = {
        "mode": mode,
        "start_date": start_date.isoformat(),
        "pattern": pattern,
        "daily_commit_count": daily_commit_count,
    }
    path = repo_path / "pattern.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[generator] 写入 {path}")


def _build_daily_pattern(daily: int, weeks: int) -> List[List[int]]:
    daily = max(0, int(daily))
    weeks = max(1, int(weeks))
    return [[daily for _ in range(weeks)] for _ in range(7)]


def _write_workflow(repo_path: Path, cfg: dict) -> None:
    workflows_dir = repo_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflows_dir / "heatmap.yml"

    data_dir = cfg.get("data_dir") or "heatmap"
    committer_name = cfg.get("committer_name", "GitHub Heatmap Bot")
    committer_email = cfg.get("committer_email", "bot@example.com")

    data_dir_literal = json.dumps(str(data_dir))
    committer_name_literal = json.dumps(str(committer_name))
    committer_email_literal = json.dumps(str(committer_email))

    workflow = f"""name: Heatmap Painter

on:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: heatmap-daily
  cancel-in-progress: false

env:
  DATA_DIR: {data_dir_literal}
  COMMITTER_NAME: {committer_name_literal}
  COMMITTER_EMAIL: {committer_email_literal}

jobs:
  paint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"
      - name: Run heatmap painter
        run: python3 tools/heatmap_painter.py
      - name: Commit and push
        run: |
          if [ -z "$(git status --porcelain)" ]; then
            echo "No changes to commit"
            exit 0
          fi
          git config user.name "$COMMITTER_NAME"
          git config user.email "$COMMITTER_EMAIL"
          git commit -am "chore: paint heatmap"
          git push
"""
    workflow_path.write_text(workflow, encoding="utf-8")
    print(f"[generator] 写入 {workflow_path}")


def _write_painter_script(repo_path: Path) -> None:
    tools_dir = repo_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    script_path = tools_dir / "heatmap_painter.py"
    script_path.write_text(_PAINTER_SCRIPT, encoding="utf-8")
    script_path.chmod(0o755)
    print(f"[generator] 写入 {script_path}")


def _write_agreement(repo_path: Path) -> None:
    agreement_path = repo_path / "AGREEMENT.md"
    agreement_path.write_text(_AGREEMENT_TEXT, encoding="utf-8")
    print(f"[generator] 写入 {agreement_path}")


_PAINTER_SCRIPT = """#!/usr/bin/env python3
import datetime as dt
import json
import os
import random
import string
import subprocess
from pathlib import Path
from typing import Optional


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    pattern_path = repo_root / "pattern.json"
    if not pattern_path.exists():
        print("pattern.json 不存在，无法继续。")
        return 1

    data = json.loads(pattern_path.read_text(encoding="utf-8"))
    try:
        start_date = dt.date.fromisoformat(data["start_date"])
    except Exception:
        print("pattern.json:start_date 无效。")
        return 1

    mode = (data.get("mode") or "pattern").lower()
    if mode not in ("pattern", "daily"):
        mode = "pattern"
    pattern = data.get("pattern") or []
    daily_goal = int(data.get("daily_commit_count") or 0)

    today = dt.datetime.utcnow().date()
    delta = (today - start_date).days
    if delta < 0:
        print("图案尚未开始。")
        return 0

    need = 0
    if mode == "daily":
        need = max(0, daily_goal)
        if need <= 0:
            print("每日定量模式未配置 daily_commit_count。")
            return 1
    else:
        if len(pattern) < 7:
            print("pattern.json:pattern 结构非法。")
            return 1
        first_row = pattern[0]
        if any(len(row) != len(first_row) for row in pattern[:7]):
            print("pattern.json:pattern 列长度不一致。")
            return 1
        cols = len(first_row)
        if cols == 0:
            print("图案宽度为 0。")
            return 0
        idx = delta
        col = idx // 7
        row = idx % 7
        if col >= cols:
            print("图案已经完成。")
            return 0
        try:
            need = int(pattern[row][col])
        except (ValueError, TypeError):
            need = 0

    identity = os.environ.get("GITHUB_ACTOR") or os.environ.get("COMMITTER_NAME")
    commits_today = _count_commits_today(repo_root, identity)
    if commits_today is None:
        return 1
    if commits_today > need:
        print(f"今日已有 {commits_today} 次提交，超过目标 {need}。请检查图案或等待明日。")
        return 1

    if need <= 0:
        print("今日像素=0，不提交。")
        return 0

    if commits_today == need:
        print("今日提交数已满足目标，跳过。")
        return 0

    data_dir = os.environ.get("DATA_DIR") or "heatmap"
    out_dir = repo_root / data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{today.isoformat()}.txt"
    existing = 0
    if out_file.exists():
        with out_file.open("r", encoding="utf-8") as handle:
            existing = sum(1 for _ in handle)

    if existing > need:
        print("heatmap 文件中的记录数已超过目标，请手动修正后重试。")
        return 1
    if existing == need:
        print("已达成目标提交数。")
        return 0

    to_write = need - existing
    with out_file.open("a", encoding="utf-8") as handle:
        for idx in range(existing + 1, existing + to_write + 1):
            stamp = dt.datetime.utcnow().isoformat()
            payload = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            handle.write(f"{stamp} #{idx}/{need} {payload}\\n")

    try:
        subprocess.run(["git", "add", str(out_file)], check=True, cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        print(f"git add 失败：{exc}")
        return 1

    print(f"已写入 {to_write} 行，等待 workflow 统一提交。")
    return 0


def _count_commits_today(repo_root: Path, identity: Optional[str]):
    today = dt.datetime.utcnow().date()
    since = dt.datetime.combine(today, dt.time.min).isoformat() + "Z"
    cmd = ["git", "log", f"--since={since}", "--pretty=%H"]
    if identity:
        cmd.append(f"--author={identity}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root, check=False)
    except FileNotFoundError:
        print("未找到 git 命令，无法检测今日提交。")
        return None
    if proc.returncode != 0:
        msg = proc.stderr.strip() or f"git log exit code {proc.returncode}"
        print(f"检查今日提交失败：{msg}")
        return None
    count = sum(1 for line in proc.stdout.splitlines() if line.strip())
    return count


if __name__ == "__main__":
    raise SystemExit(main())
"""


_AGREEMENT_TEXT = """# GitHub Heatmap Streaker AGREEMENT

By using this repository and the bundled automation you acknowledge:

1. The scripts only automate commits for styling the GitHub contribution graph. They never provide intrusion, privilege escalation, or unauthorized access capabilities.
2. You use the tooling at your own risk. Proxy usage, delegation, or unattended execution remains the user's responsibility.
3. SSH keys, personal passwords, and other credentials are never requested or persisted by this project. Only the GitHub-provided `GITHUB_TOKEN` inside Actions is used for pushes.
4. Automated commit activity may trigger GitHub anti-abuse checks. You must comply with GitHub's Terms of Service and enforce your own safeguards.
5. The project is delivered “as is” without guarantees about availability, correctness, or any form of warranty. All liabilities remain with the user.
"""


__all__ = ["save_all"]
