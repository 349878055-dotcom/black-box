# 同事接手指南（Windows 开发环境）

云端服务已部署好，你只需在 Windows 笔记本上拉代码、搭开发环境即可。

---

## 1. 克隆前必做：换行符设置

Windows 默认会把换行符转成 `\r\n`，会导致 Python 和 Shell 脚本出错。**先执行再克隆**：

```powershell
git config --global core.autocrlf input
```

然后正常克隆：

```powershell
git clone <仓库地址> personal-assistant
```

> 项目原目录名含中文（`个人助理5`），Windows 上建议用纯英文路径，如 `D:\projects\personal-assistant`，避免部分工具对中文路径报错。

如果已经克隆了才看到这条，补救：

```powershell
git config --global core.autocrlf input
git rm --cached -r .
git reset --hard
```

---

## 2. Python 环境

需要 **Python 3.10+**（推荐 3.11 或 3.12），然后：

```powershell
cd personal-assistant
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> 如果下载慢，用清华镜像：
> ```powershell
> pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
> ```

---

## 3. 需要找金涛要的文件

以下文件不在 Git 里（含密钥），需要单独拷贝：

| 文件 | 说明 |
|---|---|
| `cloud/config.json` | LLM 密钥、JWT、博查 key、skill 密钥等 |
| `cloud/models/bge-small-zh-v1.5/` | 向量检索模型（约 100MB） |

`config.json` 直接放到 `cloud/` 目录下；`models/` 文件夹整个放到 `cloud/` 下。

如果不想找人要模型，也可以自己下载：

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5', cache_folder='cloud/models')"
```

---

## 4. 本地启动云端（调试用）

正式环境已经部署在服务器上，但本地调试时可以这样跑：

```powershell
$env:PYTHONPATH = "."
python -m cloud.cloud_orchestrator.main
```

默认监听 `0.0.0.0:19000`。

---

## 5. 编译 Android App（可选）

如果需要改 App：

1. 装 **JDK 17+** 和 **Android Studio**（装好 SDK）
2. 在 `app/project/` 下新建 `local.properties`：

```properties
sdk.dir=C:\\Users\\你的用户名\\AppData\\Local\\Android\\Sdk
```

3. 编译：

```powershell
cd app\project
.\gradlew.bat :app:assembleDebug
```

---

## 6. Windows 常见坑

| 问题 | 解决 |
|---|---|
| Python/脚本报 `\r` 相关错误 | 没设 `core.autocrlf input`，见第 1 步 |
| `run.sh` 无法执行 | 这是 Linux 脚本，Windows 上用第 4 步的 PowerShell 命令 |
| 端口 19000 被占 | `netstat -ano \| findstr 19000` 查占用，或 `$env:ORCH_PORT=19001` 换端口 |
| 路径含中文报错 | 项目放纯英文路径下 |
| Gradle 下载卡住 | Android Studio 里设代理，或在 `gradle.properties` 加阿里云 Maven 镜像 |

---

## 7. 项目结构速览

```
├── cloud/                          # 云端 Python 服务
│   ├── cloud_orchestrator/
│   │   ├── main.py                 # 服务入口
│   │   ├── config.py               # 读 config.json
│   │   ├── core/                   # Agent 引擎、登录流程
│   │   ├── store/archive_center/   # Skill 仓库
│   │   └── retrieval/              # 向量检索
│   └── config.json                 # ⚠️ 不入库
├── app/                            # Android 客户端
├── tools/                          # 运维/测试脚本
├── plans/                          # 设计文档
├── requirements.txt                # Python 依赖
├── INDEX.md                        # 文件索引
└── README.md                       # 项目总览
```

详细索引见 `INDEX.md`，有问题找金涛。
