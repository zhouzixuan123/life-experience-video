# 安装与运行环境

仓库根目录就是完整 Skill。可以放在使用者的技能目录，也可以直接在此目录运行工具；项目输出放在单独的 episodes/ 目录。不要把其他版本的素材或配置复制进仓库。

使用 Python 3.10 或以上版本创建独立环境，然后安装 scripts/requirements.txt。视频处理需要 FFmpeg 与 ffprobe；Remotion 渲染需要 Node.js、npm/npx 及 assets/remotion-package-template.json 对应依赖。第三方软件、服务和模型需自行安装并遵守各自条款。

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r scripts/requirements.txt
./.venv/Scripts/python.exe -B scripts/check_portability.py --static-only
./.venv/Scripts/python.exe -B scripts/check_portability.py
```

Windows 可用 scripts/run_video_python.ps1，它默认使用本仓库 .venv；LIFE_VIDEO_PYTHON 可以指定自己的解释器。其他平台直接使用选定 Python。只有需要剪映草稿时才安装 scripts/requirements-jianying.txt。

ASR 只用于音频转写。首次使用可由 faster-whisper 下载识别模型，离线使用时传 --model-dir 指定自行准备的模型目录。模型本体不在仓库中。

字体不随包分发。Python 侧通过 LIFE_EXPERIENCE_FONT_BOLD、LIFE_EXPERIENCE_FONT_DISPLAY 指定字体，或使用 font_utils.py 发现的本机中文字体。Remotion 侧应安装同款字体并同步 TSX 中的 fontFamily；没有字体时先处理环境，不打包系统字体。

完整分发 assets/、references/、scripts/、styles/ 和 agents/ 的文本与代码文件。排除虚拟环境、模型、项目、个人素材、输出、缓存及开发者历史记录。发布前运行 check_portability.py --static-only 和 check_public_release.py。
