# 本地项目「伪编辑器」设计（v0.7.4–0.7.6）

> 源自《新奇想法.txt》（2026-11-27）：Agent 不够好用的核心原因是"看对话时看不到文件"。本项目偏开发定位，
> 参考 Cursor 的布局做一个**伪编辑器**——目录树 + 文件查看 + 对话三栏，用户只读查看，Agent 全程操作真实目录。

## 0. 定位与边界（先说清"不是什么"）

- **不是真编辑器**：不做文件编辑、保存、格式化、LSP、终端。用户改文件用自己顺手的工具直接改真实目录
  （伪编辑器看的是磁盘事实，随时刷新）。
- **不是新的存储体系**：本地项目就是**用户机器上的真实目录**（如 `D:\my-repo`）。Agent 产出的文件直接落在
  该目录，**不进** `data/generated`、不进 `file_assets`、不走 `/api/files` 下载——与现有文件体系完全解耦。
- **与现有"项目"的关系**：现有项目=工作模式的归档容器（会话/文件按 `project_id` 归属）；本地项目=Claude Code 式
  的"电脑上真实存在的项目"。两者并存、互不混用，界面上用「本地」徽标区分。
- **仅 local 模式可用**：`AUTH_MODE=cloud` 时整个功能不注册路由（远程用户看到的"本地"是服务器磁盘，毫无意义且危险）。
  这同时回答了隐私问题：**本地项目的一切数据（含元数据）只存在本机**（本地 MySQL 也是本机），登录与否都不上云、不同步，
  无需再做"只传标题"的隐私模式。

## 1. 数据模型（迁移 `0013`）

```
local_projects:
    id            PK
    user_id       int, index          # 归属（铁律：身份只来自 get_current_user_id）
    title         str(200)            # 显示名（默认取目录名）
    root_path     str(500)            # 绝对路径，注册时校验存在且是目录，此后只存不改
    allow_write   bool, default True  # 项目级"允许 Agent 写入"开关（关闭=只读助手）
    created_at / last_opened_at

conversations:  + local_project_id  int nullable, index   # 本地项目下的会话（与 project_id 互斥，建号时校验）
```

- 唯一约束 `(user_id, root_path)`：同一用户同一目录只注册一次（重复注册=提示已存在并直接打开）。
- 仓库层 `repositories/local_projects.py`（唯一 DB 访问，全部带 user_id 过滤）；
  服务层 `services/local_project_service.py`（路径安全 + 目录浏览 + 树/文件读取）。

## 2. 路径安全（本功能的命门）

**原则：root 只来自数据库行（且按 user_id 校验归属），模型/前端给的路径永远不当 root。**

```python
def safe_resolve(root: Path, rel: str) -> Path:
    anchor = root.resolve()
    p = Path(rel)
    target = (p if p.is_absolute() else anchor / p).resolve()
    if not (target == anchor or target.is_relative_to(anchor)):
        raise LocalProjectError("路径越出项目根目录")
    return target
```

- `.resolve()` 吞掉 `..` 与符号链接（Windows 也不例外），越界一律拒绝；绝对路径只要落在 root 内也接受（对话里
  出现绝对路径很自然）。
- 树/文件读取的硬上限：树单层最多 500 项（超出截断+提示）；文本文件 512 KB（超出只回元信息）；图片预览 10 MB；
  写入单文件 2 MB。
- 忽略清单（树与工具共用，`local_project_service.IGNORED_NAMES`）：`.git` `node_modules` `.venv` `venv`
  `__pycache__` `dist` `build` `.next` `.idea` `.vs`（`.gitignore` 解析留后续）。
- 明确不提供的操作：**删除、移动/重命名、执行命令**——Agent 写文件只做"创建/覆盖文本文件"。

## 3. 后端 API（`apps/api/routes/local_projects.py`，全部 `Depends(get_current_user_id)`）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/local-projects/drives` | Windows 盘符列表（选目录弹窗用） |
| GET | `/local-projects/browse?path=` | 列某目录的**子目录**（选目录逐层点选；仅 local 模式存在） |
| GET | `/local-projects` | 当前用户的本地项目列表 |
| POST | `/local-projects` | 注册 `{root_path, title?}`；校验存在+是目录+未重复；返回项目 |
| GET | `/local-projects/{id}/tree?path=&depth=1` | 单层懒加载 `[{name, type, size}]`（忽略清单生效） |
| GET | `/local-projects/{id}/file?path=` | `{kind: text\|image\|binary, content?, mime, size, truncated}` |

- **路由挂载条件**：`main.py` 里 `auth_mode == "local"` 才 `include_router`——cloud 模式下这些端点不存在（404），
  而不是存在但拒绝。
- 文件 `kind` 判定复用 `infrastructure/filetypes.py`（禁止在别处再写后缀判断）；图片返回 base64 data URI。

## 4. 工具注入（v0.7.6，对话在本地项目里跑）

沿用 `search_knowledge` 的注册闭包模式（`build_default_registry(knowledge_search=...)`）：
Chat 服务发现会话带 `local_project_id` → 取出 root 与 allow_write → 注入：

- `local_list_dir(path=".")`：列目录（忽略清单生效）
- `local_read_file(path)`：读文本（二进制如实告知"这是二进制文件"）
- `local_write_file(path, content)`：**allow_write=True 才注册**；创建/覆盖文本文件，自动建父目录；
  越界/超限/目标是目录/写进 `.git` 都拒绝并返回原因

系统提示词（`core/context.py`）在本地项目会话里追加一段：当前项目名、root、"读写一律用相对路径、你看到的是磁盘真实内容"。
工具结果即文本（"已写入 src/app.py，42 行"），**不走 artifacts 登记链路**；SSE 的 `tool_completed` 事件补带
`tool` 名（小改 `events.py`），前端据此刷新树。

## 5. 前端

- **入口**：`ProjectsModal` 新增「本地项目」区块 + 「添加本地项目」按钮（侧栏维持现状，本地项目的会话在
  普通侧栏可见、带「本地」chip，保证不进弹窗也能找到）。
- **FolderPickerModal**（新）：drives → 逐层点选子目录 → 命名并注册。全程不手输路径。
- **LocalEditorModal**（新，全屏三栏，沿用 v0.7.1 固定尺寸+内部滚动范式）：
  - 左 `FileTree`：懒加载（点开目录才请求下层），写操作后按事件刷新对应分支；
  - 中 `FileViewer`：md 走现有 `Markdown` 渲染、代码等宽、图片 base64 预览、二进制只显示元信息；
  - 右对话区：**实现取舍（v0.7.6 实际落地）**——SSE 收发完全复用服务层 `streamSSE`/`chatApi`（与主界面同一套
    逻辑，无复制）；渲染用主界面同款消息 CSS 做精简版（无版本翻页/编辑重生成/附件，属于编辑器场景刻意收窄）。
    原"抽 ChatPanel 供两处共用"的完整方案涉及主界面数百行重构，风险大于收益，推迟到主界面聊天组件化时一并做。
- 窄屏：三栏改为纵向堆叠（树折叠成顶部下拉）。

## 6. 里程碑（每步可运行，cloud 模式零影响）

| 步 | 内容 | 验收 |
|---|---|---|
| 0.7.4 注册与浏览 | 迁移 0013 + Repository/Service + drives/browse/list/create API + 前端入口与 FolderPickerModal + 项目列表区块 | 注册 `D:\某仓库` 成功、列表可见、重复注册被拦、cloud 模式下端点 404 |
| 0.7.5 伪编辑器（只读） | tree/file API + LocalEditorModal 三栏 + FileTree/FileViewer | 打开项目浏览任意文件：md 渲染、代码等宽、图片预览、大二进制如实截断 |
| 0.7.6 本地项目对话 | conversations.local_project_id + 工具注入 + ChatPanel 抽取 + 工具事件联动树刷新 + allow_write 开关 | 在伪编辑器里让 Agent 读代码并改一个文件：树即时刷新、内容可查、关开关后模型无写工具 |

## 7. 明确不做（v1 边界，防止过度设计）

删除/移动文件、命令执行、git 操作、文件变更监听（watch）、树内全局搜索、多标签文件页、云同步、任务系统接入。
后续按真实使用痛点再加（搜索与 watch 最可能先做）。
