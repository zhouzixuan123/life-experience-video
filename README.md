# 人生体验视频工作流

一个面向 Agent 的视频制作 Skill：从原创文稿与用户提供的最终配音出发，完成分镜、生图、两图冷开场、九宫格动画、字幕、混音和三种比例封面。

默认交付 1920×1080、60fps MP4，以及 4:3、3:4、16:9 三张带标题封面。此仓库是可复用工作流与工具集合，需要具备文件操作、生图和视频渲染能力的 Agent 分阶段执行。

## 开源范围

提供流程文档、Python 工具、浏览器生图辅助脚本、Remotion 开场组件及空白配置模板。不包含配音生成方案、音乐、音效、参考图片、字体、模型权重、真实项目、账号信息或开发者历史记录。

使用者自行提供有权使用的配音和其他素材。音乐和音效默认关闭；参考图可选，默认使用文字画风。视频平台和生图服务需要自己的账号与使用权限；浏览器脚本只在当前登录页面手动运行，页面结构变化后可能需要调整。

## 开始使用

1. 下载整个仓库，创建独立 Python 环境，按 [运行环境](references/runtime.md) 安装依赖并检查。
2. 将仓库作为 `produce-life-experience-videos` Skill 使用；Agent 从 [SKILL.md](SKILL.md) 开始。
3. 提供主题或原创文稿、最终配音，以及可选的授权素材。按 [命令入口](references/commands.md) 建立独立项目。
4. 依次完成音频输入、分镜图片、时间轴、渲染与封面。输入检查和最终视听确认通过后，在项目目录交付成片。

可对 Agent 说：

> 使用 $produce-life-experience-videos，根据我的原创文稿和自备配音制作视频。使用默认文字画风，不加背景音乐，先完成分镜。

## 目录

- `scripts/`：初始化、转写、字幕、混音、封面及检查工具。
- `assets/`：代码组件和空白文本模板。
- `references/`：分阶段操作要求。
- `styles/`：文字画风说明。
- `agents/`：Skill 展示信息。

代码与项目文档采用 [MIT License](LICENSE)，许可文本见 [Open Source Initiative](https://opensource.org/license/mit)。第三方依赖、服务、模型和用户素材分别适用其自身条款，见 [素材与依赖说明](THIRD_PARTY_NOTICES.md)。

## 维护验证

```text
python -B scripts/check_portability.py --static-only
python -B scripts/check_public_release.py
python -B -m unittest discover -s scripts -p "test_*.py"
```

项目、素材、缓存与凭据已配置为默认忽略。发布时只上传本仓库，不上传本地制作工作区。
