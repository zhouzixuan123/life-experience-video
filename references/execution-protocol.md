# 制作执行顺序

## 1. 建立或接手项目

在使用者选择的项目目录运行 init_episode.py。已有项目沿用原路径，不覆盖其配置和文稿。确认标题与文稿；02_配音稿.txt 只含实际朗读文字。画风、配音路径和开头时序以 00_项目配置.json 为准。

## 2. 接收最终配音

按 [audio-input.md](audio-input.md) 接收用户提供的最终音频，转写为 work/asr_processed.json，完成内容核对记录及音频输入检查。保持输入音频原样，所有时间均以这份文件为基准。

## 3. 分镜与图片

复制 assets/storyboard-template.md 为 03_分镜表.md，保持列名与 H01—H02、I01—I04、I10、S001… 编号。使用统一文字画风及可选的已授权参考图。每张图实际查看一次，填写 image_content_review.json；只针对明确大错局部修复。

## 4. 时间轴与渲染

按最终音频逐词时间填写冷开场、标题和正文入口，安装 OpeningSequence。按 timeline.md 生成 recipe.json、matches.json 和 captions.srt。正文依 visuals.md 持续推近，输出 work/silent_visual.mp4。更换音频后更新下游时序。

## 5. 混音和封面

默认直接使用自备配音，音乐和音效关闭；只有使用者明确提供素材时才按 audio-mixing.md 加入。一次混音生成 work/remix.mp4。分别生成三种比例封面底图并添加完整标题。

## 6. 成片查看与交付

创建 final_av_review.json，实际查看冷开场、九宫格、主题标题、正文和结尾，核对字幕、声音及三张封面。运行 publish_preview.py --label final 执行一次最终检查并将成片交付至项目目录。这里的发布是本地交付，不会上传社交平台。

续作只补缺失或变化的步骤；结果复用见 [incremental-execution.md](incremental-execution.md)。
