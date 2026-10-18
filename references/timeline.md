# 逐词时间轴与渲染

## 一份最终配音时间

voiceover.processed_audio 指向用户提供的最终完整音频；work/asr_processed.json 绑定其哈希并含 words。所有字幕和切图时间均来自此文件。项目所需停顿应包含在用户提供的音频中，本工具不改变语速或停顿。

每镜根据 visual_anchor_text 在实际朗读中的位置取起点；重复短句结合上下文选择出现次数。低置信、数字等价或普通识别差异先核对，不自动修改声音。同步诊断中的一帧阈值只是诊断尺度，不是日常强制返工标准。

## 字幕

正文字幕微软雅黑粗体 60px、黑描边 5px、底边距约 54px、左右至少 120px。完整短句在单行空间内就保持完整；确实超宽才按语义边界拆分，使用同一句现有词边界，不按字数均分时间。enforce_single_line_captions.py 是排版操作，传当前 ASR 与音频。

SRT 只写正文字幕；冷开场文字和品牌标题由 OpeningSequence 渲染，不重复烧录。字幕必须真实出现在最终画面中，work/captions.srt 默认不交付。

## 渲染输入

work/recipe.json 至少记录 fps=60、duration_seconds、shots。每个 S 镜头有 id、image_path、start_seconds、end_seconds、motion；所有时间均使用全片时间原点。镜头结束一般取下一实际锚点，最后一镜到配音结尾；不通过平均分配重写锚点。

work/matches.json 保存逐镜对应旁白及实际词起点，06_正文运动.json 保存焦点。motion 使用 visuals.md 的固定算法；不要让镜头算法重新安排朗读时序。

优先单个 Remotion Composition 渲染：OpeningSequence 从0帧进入，正文从品牌定格结束后进入。保持 1920×1080、原生60fps。字幕烧录后的无声画面固定为 work/silent_visual.mp4；audio-mixing.md 从该画面一次混音输出 work/remix.mp4。

只有发现明显字幕错位、切图错句、静止或抖动时，才运行对应诊断脚本。没有问题时直接进入成片确认，不再额外渲染无字幕对照或反复比较每个像素。
