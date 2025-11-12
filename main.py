from __future__ import annotations

import json
import sys
from pathlib import Path
import subprocess
import textwrap
from urllib.parse import urlparse
from typing import List

from github_streaker_tui.generator import save_all
from github_streaker_tui.gh_heatmap import show_remote_heatmap
from github_streaker_tui.tui import run_tui


CONFIG_PATH = Path(__file__).resolve().with_name("config.json")
GENERATED_ARTIFACTS = [
    "pattern.json",
    "AGREEMENT.md",
    ".github/workflows/heatmap.yml",
    "tools/heatmap_painter.py",
]
AUTO_COMMIT_MESSAGE = "chore: update heatmap workflow artifacts"


def main() -> int:
    cfg = _load_config()
    weeks = max(1, int(cfg.get("weeks", 52)))
    repo_path = Path(cfg["repo_path"])

    _show_repo_summary(repo_path)

    show_remote_heatmap(cfg.get("github_username", ""), min(30, weeks))

    pattern = _load_existing_pattern(repo_path, weeks)
    pattern, should_save = run_tui(pattern)
    if not should_save:
        print("[main] 未保存任何变更。")
        return 0

    try:
        save_all(pattern, cfg)
    except Exception as exc:
        print(f"[main] 写入目标仓库失败：{exc}")
        return 1

    print("[main] 已生成 pattern.json / workflow / tools 脚本 / AGREEMENT。")
    _auto_commit_and_push(cfg)
    return 0


def _load_config() -> dict:
    cfg = _read_config_file()
    if cfg is None:
        cfg = _bootstrap_config()

    required = [
        "repo_ssh_url",
        "repo_path",
        "github_username",
        "committer_name",
        "committer_email",
        "data_dir",
        "weeks",
    ]

    while True:
        missing = [field for field in required if not cfg.get(field)]
        if not missing:
            break
        print(f"[config] 配置缺少字段：{', '.join(missing)}。即将重新进入配置向导。")
        cfg = _bootstrap_config()

    cfg["weeks"] = max(1, int(cfg.get("weeks", 52)))
    cfg["start_from_next_sunday"] = bool(cfg.get("start_from_next_sunday", False))
    cfg["data_dir"] = cfg.get("data_dir") or "heatmap"
    repo_root = _ensure_repo(cfg)
    cfg["repo_path"] = str(repo_root)
    return cfg


def _read_config_file() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        print(f"[config] 无法解析 config.json：{exc}")
        return None


def _bootstrap_config() -> dict:
    intro = textwrap.dedent(
        """
        [config] 首次运行向导
        步骤说明：
          1. 先在 GitHub 创建目标仓库，并完成 SSH Key 绑定（可通过 `ssh -T git@github.com` 验证）。
          2. 复制该仓库的 SSH URL（形如 git@github.com:user/repo.git）。
          3. 选择一个本地目录作为仓库存放位置；如不存在，本工具会自动 `git clone <SSH URL> <路径>`。
        """
    ).strip()
    print(intro)

    repo_ssh_url, suggested_owner = _prompt_repo_ssh_url()
    repo_path = _prompt("本地仓库路径（若不存在将自动 clone）", "./heatmap-repo")
    github_username = _prompt("GitHub 用户名", suggested_owner or "")
    committer_name = _prompt("提交者昵称 (Git)", "Heatmap Bot")
    committer_email = _prompt("提交者邮件 (Git)", "bot@example.com")
    data_dir = _prompt("数据目录 (相对仓库根)", "heatmap")
    start_next = _prompt_bool("是否从下一个周日开始？(Y/n)", True)
    weeks = _prompt_int("编辑多少周宽度？(1-104)", 52, min_value=1, max_value=104)

    cfg = {
        "repo_ssh_url": repo_ssh_url,
        "repo_path": repo_path,
        "github_username": github_username,
        "committer_name": committer_name,
        "committer_email": committer_email,
        "data_dir": data_dir,
        "start_from_next_sunday": start_next,
        "weeks": weeks,
    }

    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2, ensure_ascii=False)
    print(f"[config] 已写入 {CONFIG_PATH}")
    return cfg


def _ensure_repo(cfg: dict) -> Path:
    ssh_url = cfg.get("repo_ssh_url")
    if not ssh_url:
        print("[config] repo_ssh_url 未配置，无法拉取仓库。")
        raise SystemExit(1)

    try:
        ssh_user, host, owner, repo_name = _parse_repo_ssh_url(ssh_url)
    except ValueError as exc:
        print(f"[config] 无效的 repo_ssh_url：{exc}")
        raise SystemExit(1)

    _verify_ssh_access(ssh_user, host)

    repo_path = Path(cfg["repo_path"]).expanduser()
    git_dir = repo_path / ".git"
    if git_dir.exists():
        print(f"[config] 检测到已有仓库：{repo_path}")
        return repo_path.resolve()

    if repo_path.exists():
        non_empty = any(repo_path.iterdir())
        if non_empty:
            print(f"[config] 目录 {repo_path} 已存在但不是 Git 仓库，请更换路径或清空目录。")
            raise SystemExit(1)

    repo_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[config] 本地未检测到仓库，将通过 SSH 克隆：{ssh_url}")
    try:
        subprocess.run(["git", "clone", ssh_url, str(repo_path)], check=True)
    except FileNotFoundError:
        print("[config] 未找到 git 命令，请先安装 Git 并确保其在 PATH 中。")
        raise SystemExit(1)
    except subprocess.CalledProcessError as exc:
        print(f"[config] git clone 失败：{exc}")
        raise SystemExit(1)

    print(f"[config] 仓库已克隆至 {repo_path}")
    return repo_path.resolve()


def _prompt(message: str, default: str) -> str:
    prompt = f"{message} [{default}]: "
    try:
        value = input(prompt).strip()
    except KeyboardInterrupt:  # pragma: no cover - CLI convenience
        print("\n[config] 用户中断。")
        raise SystemExit(1)
    return value or default


def _prompt_bool(message: str, default: bool) -> bool:
    while True:
        raw = _prompt(message, "Y" if default else "N").lower()
        if raw in ("y", "yes", "true", "1"):
            return True
        if raw in ("n", "no", "false", "0"):
            return False
        print("请输入 Y 或 N。")


def _prompt_int(message: str, default: int, min_value: int, max_value: int) -> int:
    while True:
        raw = _prompt(message, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if not (min_value <= value <= max_value):
            print(f"请输入 {min_value}-{max_value} 之间的数。")
            continue
        return value


def _show_repo_summary(repo_path: Path) -> None:
    print(f"[repo] 当前仓库：{repo_path}")
    status_proc = _run_git(repo_path, ["status", "-sb"], capture_output=True, check=False)
    if status_proc.returncode == 0:
        status = status_proc.stdout.strip() or "干净，无改动。"
        print(f"[repo] 状态：\n{status}")
    else:
        print(f"[repo] 无法获取状态：{status_proc.stderr.strip() if status_proc.stderr else status_proc.returncode}")

    log_proc = _run_git(
        repo_path,
        ["log", "-1", "--oneline", "--decorate"],
        capture_output=True,
        check=False,
    )
    if log_proc.returncode == 0 and log_proc.stdout.strip():
        print(f"[repo] 最近一次提交：{log_proc.stdout.strip()}")
    else:
        print("[repo] 尚无提交记录。")


def _load_existing_pattern(repo_path: Path, weeks: int) -> List[List[int]]:
    weeks = max(1, int(weeks or 1))
    pattern_path = Path(repo_path) / "pattern.json"
    if not pattern_path.exists():
        print("[pattern] 未找到 pattern.json，使用空白模板。")
        return _blank_pattern(weeks)

    try:
        data = json.loads(pattern_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[pattern] 读取 pattern.json 失败：{exc}，使用空白模板。")
        return _blank_pattern(weeks)

    raw_pattern = data.get("pattern")
    if not isinstance(raw_pattern, list) or len(raw_pattern) != 7:
        print("[pattern] pattern.json 结构异常，使用空白模板。")
        return _blank_pattern(weeks)

    normalized: List[List[int]] = []
    for row_idx, row in enumerate(raw_pattern):
        if not isinstance(row, list):
            print(f"[pattern] 第 {row_idx + 1} 行非法，使用空白模板。")
            return _blank_pattern(weeks)
        normalized_row: List[int] = []
        for value in row:
            try:
                normalized_row.append(int(value))
            except (TypeError, ValueError):
                normalized_row.append(0)
        normalized.append(normalized_row)

    adjusted = _resize_pattern(normalized, weeks)
    print("[pattern] 已载入现有 pattern.json。")
    return adjusted


def _blank_pattern(weeks: int) -> List[List[int]]:
    return [[0 for _ in range(weeks)] for _ in range(7)]


def _resize_pattern(pattern: List[List[int]], weeks: int) -> List[List[int]]:
    adjusted: List[List[int]] = []
    for row in pattern:
        row_copy = list(row[:weeks])
        if len(row_copy) < weeks:
            row_copy.extend([0] * (weeks - len(row_copy)))
        adjusted.append(row_copy)
    # 如果 pattern 少于 7 行，补零；多于 7 行则截断
    if len(adjusted) < 7:
        adjusted.extend(_blank_pattern(weeks)[len(adjusted):])
    elif len(adjusted) > 7:
        adjusted = adjusted[:7]
    return adjusted


def _auto_commit_and_push(cfg: dict) -> None:
    repo_path = Path(cfg["repo_path"])
    print("[git] 正在自动提交并推送生成文件...")

    staged_any = False
    for relative in GENERATED_ARTIFACTS:
        target = repo_path / relative
        if not target.exists():
            continue
        try:
            _run_git(repo_path, ["add", relative], capture_output=False, check=True)
            staged_any = True
        except subprocess.CalledProcessError as exc:
            print(f"[git] git add {relative} 失败：{exc}")

    if not staged_any:
        print("[git] 没有可暂存的文件，跳过自动提交。")
        return

    diff_proc = _run_git(
        repo_path,
        ["diff", "--cached", "--name-only"],
        capture_output=True,
        check=True,
    )
    if not diff_proc.stdout.strip():
        print("[git] 暂存区无变化，跳过提交。")
        return

    try:
        _run_git(
            repo_path,
            ["config", "user.name", cfg["committer_name"]],
            capture_output=False,
            check=True,
        )
        _run_git(
            repo_path,
            ["config", "user.email", cfg["committer_email"]],
            capture_output=False,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"[git] 设置提交者信息失败：{exc}")

    commit_proc = _run_git(
        repo_path,
        ["commit", "-m", AUTO_COMMIT_MESSAGE],
        capture_output=True,
        check=False,
    )
    combined_commit = (commit_proc.stdout or "") + (commit_proc.stderr or "")
    if commit_proc.returncode != 0:
        if "nothing to commit" in combined_commit.lower():
            print("[git] 没有需要提交的更改。")
            return
        print("[git] git commit 失败：")
        if combined_commit.strip():
            print(combined_commit.strip())
        return

    if combined_commit.strip():
        print(combined_commit.strip())

    push_proc = _run_git(repo_path, ["push"], capture_output=True, check=False)
    if push_proc.returncode == 0:
        print("[git] 推送成功。")
        return

    _diagnose_push_failure(push_proc, cfg)


def _diagnose_push_failure(proc: subprocess.CompletedProcess, cfg: dict) -> None:
    combined = (proc.stdout or "") + (proc.stderr or "")
    print("[git] 推送失败，以下是 git 输出：")
    if combined.strip():
        print(combined.strip())
    else:
        print(f"(exit code {proc.returncode})")

    lower = combined.lower()
    ssh_hint = cfg.get("repo_ssh_url", "")
    if "permission denied" in lower and "publickey" in lower:
        print(
            "[hint] GitHub 拒绝了 SSH 公钥。请确保已在当前环境中配置 SSH Key，"
            " 并运行 `ssh -T git@github.com` 验证后重试。"
        )
        if ssh_hint:
            print(f"[hint] 当前仓库 URL：{ssh_hint}")
        return

    if "repository not found" in lower:
        print("[hint] GitHub 无法找到远端仓库，请确认 SSH URL 是否正确且大小写匹配。")
        return

    if "updates were rejected" in lower:
        print("[hint] 远端存在本地没有的提交，请在目标仓库执行 `git pull --rebase` 后再试。")
        return

    print("[hint] 请手动在仓库目录运行 `git status` / `git push` 获取更多信息。")


def _run_git(
    repo_path: Path,
    args,
    *,
    capture_output: bool,
    check: bool,
) -> subprocess.CompletedProcess:
    cmd = ["git"] + args
    try:
        return subprocess.run(
            cmd,
            cwd=repo_path,
            text=True,
            capture_output=capture_output,
            check=check,
        )
    except FileNotFoundError:
        print("[git] 未找到 git 命令，请安装 Git 并确保其在 PATH 中。")
        raise SystemExit(1)


def _prompt_repo_ssh_url() -> tuple[str, str]:
    while True:
        repo_ssh_url = _prompt("仓库 SSH URL", "git@github.com:username/heatmap.git").strip()
        try:
            _ssh_user, _host, owner, _repo = _parse_repo_ssh_url(repo_ssh_url)
            return repo_ssh_url, owner
        except ValueError as exc:
            print(f"[config] SSH URL 无效：{exc}")


def _parse_repo_ssh_url(ssh_url: str) -> tuple[str, str, str, str]:
    if not ssh_url:
        raise ValueError("地址不能为空。")

    url = ssh_url.strip()
    ssh_user = "git"
    host = ""
    path = ""

    if url.startswith("git@"):
        try:
            user_host, path = url.split(":", 1)
            ssh_user, host = user_host.split("@", 1)
        except ValueError as exc:
            raise ValueError("格式应为 git@host:owner/repo.git") from exc
    elif url.startswith("ssh://"):
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.path:
            raise ValueError("ssh:// URL 需包含主机与路径。")
        host = parsed.hostname
        ssh_user = parsed.username or "git"
        path = parsed.path.lstrip("/")
    else:
        raise ValueError("仅支持 git@host:path 或 ssh://host/path 形式。")

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if "/" not in path:
        raise ValueError("路径需包含 owner/repo。")
    owner, repo = path.split("/", 1)
    repo = repo or ""

    if not host:
        raise ValueError("未解析到主机名。")

    return ssh_user or "git", host, owner, repo


def _verify_ssh_access(ssh_user: str, host: str) -> None:
    if not host:
        return
    target = f"{ssh_user}@{host}" if "@" not in host else host
    print(f"[config] 正在验证 SSH 连接：ssh -T {target}")
    cmd = [
        "ssh",
        "-T",
        target,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("[config] 未找到 ssh 命令，请安装 OpenSSH 客户端并重试。")
        raise SystemExit(1)

    combined = (result.stdout or "") + (result.stderr or "")
    lower = combined.lower()
    if "successfully authenticated" in lower:
        print("[config] SSH 验证通过。")
        return

    guidance = "[config] SSH 验证失败。"
    if "permission denied" in lower:
        guidance += f" GitHub 未接受你的公钥，请运行 `ssh -T {target}` 并在 GitHub Settings › SSH Keys 中添加/更新公钥。"
    elif "could not resolve hostname" in lower:
        guidance += f" 无法解析主机 {host}，请检查网络或代理配置。"
    elif "host key verification failed" in lower:
        guidance += f" 未信任该主机，请先运行 `ssh -T {target}` 手动接受指纹。"
    elif "no such file or directory" in lower:
        guidance += " 请确认 ssh 可执行文件存在且已加入 PATH。"
    else:
        guidance += f" 请手动运行 `ssh -T {target}` 以查看更多提示。"

    print(guidance)
    if combined.strip():
        print("[config] SSH 输出：")
        print(combined.strip())
    raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(main())
