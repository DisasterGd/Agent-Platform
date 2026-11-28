# 打包 exe 并发布到 GitHub（v0.9）

本文教你如何把 Agent Platform 打包成**单文件 exe**，并发布到 GitHub Release 供任何人下载、双击即用。

## 0. 前置

- Windows 本机：Python 3.12、Node.js、MySQL（**构建** exe 不需要 MySQL，**运行**需要）。
- 后端依赖已装（含打包器）：`cd backend && pip install -e ".[dev]"`。
- 前端已构建：`cd frontend && npm install && npm run build`。

## 1. 打包 exe

在**仓库根目录**执行：

```powershell
.\.venv\Scripts\python.exe scripts\build_exe.py
```

产物：`dist/AgentPlatform.exe`（单文件，几十 MB）。`build/` 是中间产物，已 gitignore。

## 2. 本地自测（模拟用户）

1. 把 `dist/AgentPlatform.exe` 复制到一个**干净目录**（模拟新用户）。
2. 双击运行：首次会在此目录生成 `.env` 并用记事本打开，填好数据库口令 / 可选的 `LLM_API_KEY` 后重新运行。
3. 确认浏览器自动打开 `http://127.0.0.1:8000`，且能正常对话。
4. 依赖 MySQL 已启动且已建库；若提示「数据库迁移失败」，先查 MySQL 与 `.env`。

## 3. 发布到 GitHub（网页版）

1. 提交并推送代码：

   ```powershell
   git add -A
   git commit -m "feat: ..."
   git push
   ```

2. 打 tag 并推送（建议 `v0.9.1`）：

   ```powershell
   git tag v0.9.1
   git push origin v0.9.1
   ```

3. 打开仓库页面 → **Releases** → **Draft a new release**。
4. 「Choose a tag」选 `v0.9.1`；标题填 `v0.9.1`；说明里贴本次更新点。
5. **Attach binaries** 上传 `dist/AgentPlatform.exe`。
6. 点 **Publish release**。

## 4. 发布到 GitHub（gh CLI，更快）

```powershell
gh auth login
gh release create v0.9.1 dist/AgentPlatform.exe --title "v0.9.1" --notes "首个桌面双击启动版"
```

## 5. 注意事项

- **exe 仍依赖本机 MySQL**：下载者需自备 MySQL 并建库（见 README「初始化数据库」）。要彻底免依赖，得换 SQLite/嵌入式数据库，属后续工作。
- **SmartScreen**：未签名 exe 首次运行 Windows 可能提示「未知发布者」，点「更多信息 → 仍要运行」即可；要消除需购买代码签名证书（个人阶段可先不签）。
- **别提交**：`dist/`、`build/` 已在 `.gitignore`；`.env` 含密钥绝不提交。
- **开源**：仓库已含 `LICENSE`（MIT），发布时保留即可；`.env.example` 是公开模板，不含真实密钥。

> 进阶：想要「推送 tag 自动构建 exe 并附到 Release」，可加一个 GitHub Actions（Windows 流水线跑 `build_exe.py`）。需要的话我再补。
