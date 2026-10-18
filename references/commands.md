# 命令入口

以下在仓库根目录执行。把示例主题、路径替换成当前项目；Windows 示例使用 .venv，其他平台使用相应解释器。

```powershell
$videoPython = (Resolve-Path './.venv/Scripts/python.exe').Path
$videoProject = Join-Path (Get-Location) 'episodes/demo'
$videoFfmpeg = (Get-Command ffmpeg).Source
& $videoPython -B scripts/init_episode.py $videoProject --title '第一次值夜班'
& $videoPython -B scripts/production_workflow.py $videoProject prepare
```

将确认文稿写入项目文件，并放入自行准备的 配音/narration.wav。按项目所需结构核对完整音频，不由本工具生成。

```powershell
$videoVoice = Join-Path $videoProject '配音/narration.wav'
& $videoPython -B scripts/transcribe_voice.py $videoVoice "$videoProject/work/asr_processed.json" --model small
& $videoPython -B scripts/validate_audio_input.py $videoProject --audio $videoVoice --asr "$videoProject/work/asr_processed.json" --prepare
# 实际核对后，填写 work/audio_input_review.json 的 content_matches_script。
& $videoPython -B scripts/production_workflow.py $videoProject check --stage voice --audio $videoVoice --asr "$videoProject/work/asr_processed.json" --review-mode machine_only
```

填写分镜表后检查格式；网页生图只选当前使用平台的生成器。默认无需参考图；使用参考图时按 visuals.md 配置并实际上传。

```powershell
& $videoPython -B scripts/validate_storyboard_md.py "$videoProject/03_分镜表.md" --project-dir $videoProject
& $videoPython -B scripts/build_chatgpt_f12_script.py $videoProject
# 或：scripts/build_gemini_f12_script.py
& $videoPython -B scripts/validate_image_review.py $videoProject --prepare
# 实际看图后填写记录。
& $videoPython -B scripts/production_workflow.py $videoProject check --stage images
& $videoPython -B scripts/production_workflow.py $videoProject prepare --motion-plan
```

当前 Remotion 项目需包含 package.json/src。用实际图片路径替换以下占位符，并按最终音频填写开头时序。字幕排版、渲染要求见 timeline.md；本工作流需要 Agent 生成本期时间轴和 Composition，并非一个命令完成视频。

```powershell
& $videoPython -B scripts/prepare_nine_grid_intro.py '<Remotion项目>' '<I01.png>' '<I02.png>' '<I03.png>' '<I04.png>' --hook-images '<H01.png>' '<H02.png>' --theme '<I10.png>' --episode-config "$videoProject/00_项目配置.json"
& $videoPython -B scripts/enforce_single_line_captions.py "$videoProject/work/captions.srt" --asr "$videoProject/work/asr_processed.json" --audio $videoVoice --font-size 60 --horizontal-margin 120
```

当前 Composition 渲染为 work/silent_visual.mp4 后，以真实音频时长替换下面的秒数。默认不加背景音乐或音效；需要时再传 --source 和 --intro-sfx。

```powershell
& $videoPython -B scripts/build_looping_bgm_plan.py $videoProject --duration 120 --ffmpeg $videoFfmpeg --voice $videoVoice --output "$videoProject/work/audio_plan.json"
& $videoPython -B scripts/compose_audio_mix.py $videoProject "$videoProject/work/audio_plan.json" --ffmpeg $videoFfmpeg
& $videoPython -B scripts/build_cover_variants.py $videoProject --prepare
# 完成 cover_prompts.json 中三项独立封面生图后排版。
& $videoPython -B scripts/build_cover_variants.py $videoProject
& $videoPython -B scripts/validate_final_delivery.py $videoProject --prepare
# 实际查看成片与封面，填写 final_av_review.json 后本地交付。
& $videoPython -B scripts/publish_preview.py $videoProject --label final
```

缺图、字幕错句、运动异常时按需运行对应检查器。明确索要剪映草稿时运行 build_jianying_project.py；普通制作不重复运行全部维护测试。
