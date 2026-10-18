# 用户提供的音频

本工作流接收用户已经准备好的最终完整音频，不生成配音、不连接配音服务、不改变音色、语速或停顿。音频应与确认文稿一致，包含项目所需的开头、主题和正文，并具有相应使用权限。

把文件保存到项目 配音/narration.wav，或将实际路径写入 00_项目配置.json 的 voiceover.processed_audio。processed_audio 是兼容下游工具的字段名，表示最终采用的音频，不代表脚本会对输入进行后处理。voiceover.mode 为 user_supplied。

transcribe_voice.py 只把音频转为字幕和切图所需的逐词时间，结果保存到 work/asr_processed.json；识别模型由使用者另行安装或下载。不从字数推算时间。

运行 validate_audio_input.py --prepare 创建 work/audio_input_review.json，核对音频与确认稿后将 content_matches_script 改为 true。记录绑定当前音频、ASR 和文稿哈希，文件变化后重新准备和核对。再运行 production_workflow.py check --stage voice；voice 是兼容的音频输入检查阶段名。

检查器验证音频可解码、逐词时间有效及内容核对记录当前有效。它不判断发音或听感，不生成、补录或修复音频。输入存在缺句、错序等明确问题时，请使用者提供修订文件；更换音频后更新 ASR、字幕和时间轴。
