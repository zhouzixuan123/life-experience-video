---
name: produce-life-experience-videos
description: 使用原创或已授权文稿、用户提供的配音与素材，制作人生体验类视频，完成分镜、生图、两图冷开场、九宫格、字幕、混音和封面。
---

# 人生体验视频制作（开源版）

只执行用户要求的阶段。默认输出 1920×1080、16:9、60fps MP4 和三张带标题封面。此版本从用户提供的最终配音文件开始，不包含配音生成能力或配音服务配置。

制作、续作、改片先读 [执行顺序](references/execution-protocol.md)，命令见 [命令入口](references/commands.md)，安装见 [运行环境](references/runtime.md)。项目输入应为原创或已获得所需使用许可的内容；音乐、音效、图片、字体和模型不随包提供。

| 阶段 | 参考 |
|---|---|
| 文稿 | [写作](references/writing.md) |
| 外部音频输入 | [输入要求](references/audio-input.md) |
| 分镜、画风、镜头 | [画面](references/visuals.md) |
| 生图平台操作 | [平台](references/image-generation-modes.md) |
| 冷开场、九宫格、标题 | [开头](references/intro-template.md) |
| 逐词时间、字幕、渲染 | [时间轴](references/timeline.md) |
| 可选音乐和音效 | [混音](references/audio-mixing.md) |
| 局部修复 | [有限修复](references/quality-review.md) |
| 三种比例封面 | [封面](references/covers.md) |
| 成片交付 | [交付](references/delivery.md) |
| 用户明确要求可编辑草稿 | [剪映导出](references/jianying-draft.md) |

每张图保存后实际查看一次；成片输出后查看开头、正文字幕、声音和封面，再运行一次发布检查。只修有确定证据的大错，每处最多一轮局部修复并保留回退原件。没有实际看图或听音时不填写已完成对应审核。

默认只有文字画风，不需要参考图片；有参考图时先确认使用权限，实际查看后填写 style_prompt 和 style_reference。背景音乐和音效默认关闭，只有明确提供相应文件才启用。
