# GitHub Heatmap Streaker TUI

本项目提供一个可本地运行的 Python TUI，用来设计 GitHub 贡献热力图图案（7×N 矩阵），生成所需脚本与 GitHub Actions 工作流，并通过自动提交让图案在指定日期开始按天成型。

## 功能亮点

- **热力图抓取与预览**：调用 `requests` 获取 `https://github.com/users/<username>/contributions`，解析 SVG 并以 ANSI/ASCII 形式显示最近 N 周的真实贡献情况。
- **curses TUI 网格编辑器**：固定 7 行（周日→周六）、列宽可配置（默认 52 周），提供方向键/WASD、数字、空格、`C`、`S`、`Q` 等操作，实时显示光标位置与当前值。
- **一键生成工具链**：在目标仓库内写入 `pattern.json`、`.github/workflows/heatmap.yml`、`tools/heatmap_painter.py` 和 `AGREEMENT.md`。所有提交动作仅由 GitHub Actions 使用 `GITHUB_TOKEN` 执行。
- **日期对齐**：支持立即开始或从下一个周日起算的 `start_date`，自动校验像素矩阵尺寸，防止错位。
- **风险提示**：`AGREEMENT.md` 内含免责声明，提醒使用者遵守 GitHub TOS、自担风险、脚本仅做热力图美化。

## 运行环境

- Python 3.8+
- Git CLI，且已完成 GitHub SSH 配置（可用 `ssh -T git@github.com` 验证）
- 依赖：`requests`；若在 Windows 运行 TUI，还需 `windows-curses`
  ```bash
  pip install requests
  # Windows:
  pip install windows-curses
  ```

建议创建虚拟环境：
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install requests windows-curses  # 视平台而定
```

## 快速开始

0. **准备 SSH 与远端仓库**  
   - 在 GitHub 创建目标仓库，并确保 GitHub Actions 已启用。  
   - 生成并添加 SSH Key 到 GitHub 账号，终端中 `ssh -T git@github.com` 应显示成功信息。  
   - 复制仓库的 SSH URL，例如 `git@github.com:username/heatmap-art.git`。

1. **首次运行**  
   ```bash
   python main.py
   ```
   若 `config.json` 不存在，将交互式询问以下字段并写入：
   - `repo_ssh_url`: 仓库 SSH 地址（`git@github.com:...`），用于自动 `git clone`，并可从中解析仓库 owner
   - `repo_path`: 本地仓库路径；若该目录不存在或为空，会用 SSH URL 自动 `git clone`
   - `github_username`: GitHub 用户名（用于抓取真实热力图）；默认值会自动取 `repo_ssh_url` 中的 owner
   - `committer_name`, `committer_email`: GitHub Actions 提交者信息
   - `data_dir`: 自动提交写入的目录（默认 `heatmap`）
   - `mode`: `pattern`（图案模式）或 `daily`（每日定量模式）
   - `start_from_next_sunday`: 仅在 `pattern` 模式下询问，控制是否从下一个周日开始
   - `daily_commit_count`: 仅在 `daily` 模式下询问，每天提交多少次
   - `weeks`: TUI 网格列数（周数，默认 52，范围 1-104）

   ### 初始化向导提示
   1. `repo_ssh_url` 与 `repo_path` 共同决定“本地仓库 ←→ GitHub 仓库”的映射。若本地路径不存在，本工具会直接执行 `git clone <SSH URL> <路径>`；因此请确保本机 Git 与 SSH 已配置，并拥有该仓库写权限。  
   2. 程序会在 clone 前自动执行 `ssh -T git@<host>` 验证，若失败会输出错误日志并给出补救指引（例如添加 SSH Key、手动接受 host key、检查网络等）。  
   3. 其余字段可随时在 `config.json` 中调整；当缺少字段时程序会自动重新进入向导，以避免配置不完整。  
   4. 向导会将填写结果保存到 `config.json`，后续运行将复用这些设置。

2. **热力图预览 & 仓库状态检查**  
   每次运行都会先打印目标仓库的 `git status -sb` 以及最近一次提交，便于了解当前状态；随后抓取 GitHub 热力图并以彩色/ASCII 输出。若抓取失败会提示但不会中断流程。

3. **编辑图案（pattern 模式）或确认每日模式**  
   - `pattern` 模式：进入 curses TUI。若目标仓库已有 `pattern.json`，会自动读取并填充到编辑器中，方便在原图基础上微调；否则使用 `7×weeks` 的全 0 网格。TUI 支持文字模板功能，可在任意列输入字符串并生成 5×7 点阵。完成后按 `Ctrl+S` 保存或 `Q` 放弃。  
   - `daily` 模式：无需编辑图案，程序会提示“每天 X 次提交，立即生效”，并直接生成所需脚本。

4. **生成文件**  
   保存后调用 `save_all` 将以下文件写入 `repo_path`：
   - `pattern.json`: 包含 `start_date` 与 7×N `pattern`
   - `.github/workflows/heatmap.yml`: 每 30 分钟运行一次的 Actions workflow
   - `tools/heatmap_painter.py`: 当天“像素”需要提交多少行数据，由 workflow 调用
   - `AGREEMENT.md`: 免责声明

5. **自动提交与推送**  
   保存成功后，程序会自动 `git add` / `commit`（提交信息：`chore: update heatmap workflow artifacts`）并尝试 `git push`。  
   - 若推送失败且输出包含 `Permission denied (publickey)`，请重新检查 SSH Key 并运行 `ssh -T git@github.com` 验证；程序会把 git 原始输出打印出来，方便排查。  
   - 如果远端有新的提交导致冲突，会给出“先 pull 再试”的提示。  
   - 若希望自行处理，可直接在仓库目录运行常规 git 命令。

6. **验证 GitHub Actions**  
   推送完成后，前往 GitHub 仓库 → **Actions → Heatmap Painter**，手动触发一次 `workflow_dispatch` 或等待定时任务：  
   - 日志显示 “已写入 X 行” 即为成功；  
   - 若日志提示 “今日已有 X 次提交，超过目标 Y”，workflow 会失败，并且程序会在仓库中自动创建一个 issue，将报错信息和 `@GitHub 用户名` 一起提醒，确保你能及时关注。

## TUI 操作说明

| 按键 | 功能 |
| ---- | ---- |
| ↑ / `W` | 光标上移 |
| ↓ / `s` | 光标下移 |
| ← / `A`, → / `D` | 光标左右移动 |
| `0-9` | 将当前格子设置为对应提交次数 |
| 空格 | 在 0 与 5 之间切换 |
| `C` / `c` | 按序循环 0 → 3 → 6 → 9 → 0 |
| `T` | 文字模板，从当前列开始生成 5×7 点阵文本（填充值=9） |
| `X` | 清空整个图案（会弹出确认） |
| `Ctrl+S` | 保存并退出 |
| `Q` | 放弃修改退出 |

终端不支持 TTY 或缺少 `curses`（Windows 未安装 `windows-curses`）时会自动放弃编辑并提示安装方法。TUI 内的每个格子会根据提交数量自动套用 GitHub 热力图的绿色背景梯度，方便预览成品效果。保存快捷键为 `Ctrl+S`，避免与 `S` 向下移动冲突。

## 生成文件详情

- `pattern.json`  
  ```json
  {
    "mode": "pattern",
    "start_date": "YYYY-MM-DD",
    "pattern": [[...7 rows...]],
    "daily_commit_count": 0
  }
  ```
  `mode` 决定 painter 的行为：  
  - `pattern`：按 7×N 图案逐日绘制。`start_date` 由「是否从下一个周日开始」控制。  
  - `daily`：忽略图案、直接按 `daily_commit_count` 每天提交固定次数，并立即生效（start_date = 生成当天）。

- `.github/workflows/heatmap.yml`  
  - 触发：每 30 分钟 + `workflow_dispatch`
  - 权限：`permissions.contents: write`
  - 并发：`heatmap-daily`
  - 步骤：checkout → setup-python → `python3 tools/heatmap_painter.py` → 若有改动则 config user + commit + push
  - 环境变量：`DATA_DIR`, `COMMITTER_NAME`, `COMMITTER_EMAIL`

- `tools/heatmap_painter.py`  
  - UTC 日期与 `start_date` 对比，算出当天索引（列×行）  
  - 若图案尚未开始 / 已完成 / 当前像素为 0，直接退出  
  - `daily` 模式下忽略图案，直接使用 `daily_commit_count` 作为目标，并不会等待周日  
  - 在写入前会根据 `GITHUB_ACTOR`（或配置的 GitHub 用户名）检查当日已有的提交次数，若已达到/超过目标则终止并调用 GitHub API 创建新的 issue，同时 `@用户名`，从而在仓库中留下可追踪的提醒  
  - 根据 `DATA_DIR` 写入 `${DATA_DIR}/YYYY-MM-DD.txt`，不足的行数将补写随机内容  
  - 完成后执行 `git add` 目标文件，真正的 commit/push 由 workflow 统一处理  
  - 只依赖 `GITHUB_TOKEN`；不会接触本地 SSH 私钥或用户凭据

- `AGREEMENT.md`  
  强调自动化仅用于热力图美化、用户自担风险、不得违反 GitHub TOS、工具按“现状”提供等注意事项。

## 常见问题

- **ModuleNotFoundError: `_curses`**  
  Windows 默认缺少 curses。请在虚拟环境中运行 `pip install windows-curses`，或使用 WSL/Linux/macOS。

- **requests 未安装**  
  运行 `pip install requests`。抓取失败时程序会输出错误并继续，让你仍可编辑图案。

- **终端太窄**  
  当 TUI 无法完整显示全部列，会尽量绘制可见内容；可扩大终端宽度或减少 weeks。

## 下一步

1. 确认 `ssh -T git@github.com` 可用，并在向导中填写正确的 `repo_ssh_url` 与 `repo_path`，让工具自动 clone。
2. 运行 TUI 并保存图案后，关注程序自动 push 的输出；若失败，请按提示完成 SSH/权限配置后重试或手动运行 git 命令。
3. 在 GitHub Actions 中手动触发 “Heatmap Painter” workflow 并检查日志；若因超额提交失败，按照自动创建的 issue 指引处理。
4. 等待 `start_date` 到来，观察热力图是否按预期变化。

如有改进需求（例如新增图案、修改宽度、调整 workflow 频率），重新运行 `python main.py`、保存新图案并再次提交即可。
