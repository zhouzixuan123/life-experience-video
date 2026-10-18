# 续作和结果复用

production_workflow.py prepare 只补缺失记录，--motion-plan 从已填写分镜生成焦点初稿。新项目使用 init_episode.py；已有记录不覆盖。

status 查看进度；check --stage voice 验证用户音频输入，check --stage images 验证图片查看记录。音频、参数和识别模型未变时复用 ASR；输入变化时重新识别。画风参考为可选输入，变更后刷新相应图片记录。

换音乐从明确提供的源素材重混。publish_preview.py 在本地交付前执行最终检查；历史通过不代替当前文件检查。storyboard、sync、motion、shots、captions 仅用于对应问题诊断。
