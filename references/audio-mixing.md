# 配音与可选背景音混合

仓库不包含音乐或音效。默认 music.enabled=false、segments=[]、sound_effects=[]，仅使用用户提供的配音。不要从完整版、其他项目或网络自动取用替代素材。

build_looping_bgm_plan.py 显式接收 --source 后才启用背景音乐；从音源0秒循环到结尾，默认音量0.12。明确提供 --intro-sfx 时才加入片头音效，起点按 cold_hook.duration_frames / intro.fps 计算。未提供的项目保持关闭。

compose_audio_mix.py 从无声画面、配音及明确提供的音乐音效一次重建 work/remix.mp4。修改音乐时从源文件重混，避免反复叠加声音。音乐、音效的使用权限由提供者确认，其许可与本项目代码许可分别适用。
