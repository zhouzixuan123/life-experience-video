# 剪映草稿导出

只有用户明确要求时执行。先完成普通 MP4 制作，导出脚本读取当前通过的 recipe 和音频计划，不重新选择配音、估算时间，也不覆盖 work/recipe.json、matches.json 或 validation.json。

build_jianying_project.py 输出 work/jianying_draft，使用副本素材。正文图片、已有关键帧、字幕和声音轨道可编辑；复杂开头保留为当前合成画面的一段视频片段，不承诺拆成全部动画层。

需要 scripts/requirements-jianying.txt 中的可选依赖。导出前确认当前 recipe 具有全片起止时间、图路径与 motion，audio_mix.plan 指向实际采用的混音计划。缺信息时报告缺项，不从静音或平均语速重建。

交付时 publish_preview.py --include-draft 将素材复制到最终成片/剪映草稿并改写路径。正式工程保持一个当前版和一个回退版。
