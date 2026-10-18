# 两图冷开场与九宫格

## 当前模板

固定顺序：H01 承接节拍 1—2，H02 承接节拍 3—4；第四节拍读完后第二张图和字幕保留约 0.5 秒；随后四个运动层进入九宫格，再落到 I10 主题定格和标题。

prepare_nine_grid_intro.py 安装 assets/two-shot-cold-hook 与 assets/nine-grid-intro；完整 Composition 从第 0 帧直接挂载 OpeningSequence。开头运动参数只由 assets/nine-grid-intro/motion-spec.json 提供，安装脚本和 TSX 共用，不在项目中各改一套。

## 按配音填写的参数

intro.cold_hook.caption_beats 的四个文本来自确认稿，start_frame/end_frame 来自 用户提供的最终音频的实际开口；image_switch_frames 为 [0, 节拍3起点]。post_hook_pause_frames 默认 30（60fps），duration_frames 等于第四节拍结束帧加这段留白。

品牌标题 topic_lines 拼接后等于配置 title，包含红色重点词。topic_reveal_frame 在主题图运动完成后，title_voice_start_frame 与它相同。默认品牌片头至少 300 帧；标题读完再保留 0.15 秒，必要时延长定格。品牌入口 = cold_hook.duration_frames / fps；正文入口再加 intro.duration_frames / fps。

安装器根据共用运动参数计算标题最早时刻。源时间参数不由每期自由调整。用户提供的音频需要包含匹配开头结构的时间空间；按其实际时间填写。输入无法配合结构时说明具体时间差，由使用者调整输入。

## 文字与构图

冷开场字幕黄、红、黄、红，第一条中上偏左、第二条中下偏右，在同一张图上累积显示。微软雅黑粗体默认 88px、8px 黑描边，无阴影和底板。安装器按字体测量为长字幕逐条缩小字号，保持原文；超出可用布局才报告排版问题，不改写文稿。

主题底图人物与主要道具在左，主题字在右，中文由后期渲染。音乐和片头音效为可选输入，默认关闭；配置见 audio-mixing.md。

## 实际确认

不额外生成比较用视频。成片输出后直接查看冷开场、九宫格运动中段、主题标题这三个位置，确认结构存在、人物未遮字，再填写 final_av_review.json 的 opening_complete。文件存在或两视频相似不能替代这一步。
