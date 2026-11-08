# Skill agen di repo ACEVIDS

| Skill | Asal | Untuk apa |
|---|---|---|
| `acevids-editor` | ACEVIDS | memakai server upload/cek/render lewat API |
| `ffmpeg-skill` | kajisho5/ffmpeg-skill (MIT) | 42 alat ffmpeg terverifikasi: probe, cut, join, silence, fit, caption, overlay, color, audio, loudness, export, check, look, render project |
| `auto-editor`, `auto-editor-effects`, `auto-editor-export`, `auto-editor-transcribe`, `auto-editor-transitions` | WyattBlue/auto-editor (Unlicense) | CLI potong otomatis (audio/motion/blackdetect), ekspor ke NLE |
| `cut-silences`, `cut-mistakes`, `edit-video`, `video-storytelling`, `short-form-edit` | nateherkai/herk-edit-kit (MIT) | pipeline edit talking-head berbasis transkrip kata; reel 9:16 |
| `business-motion-film` | echris6/motion-video-kit (MIT) | iklan motion premium + loop kritik "Gauntlet" |
| `openstoryline-install`, `openstoryline-use` | FireRedTeam/FireRed-OpenStoryline (Apache-2.0) | agen cerita vlog/iklan dengan LLM/VLM |

Tidak di-vendor, pasang bila perlu:

```bash
npx skills add remotion-dev/skills                       # motion graphics React
npx skills add 0xsline/OpenChatCut --skill openchatcut   # editor GUI agen-native (AGPL)
```

Catatan untuk skill herk-edit-kit: script pembantu yang mereka rujuk sebagai
`scripts/transcribe-elevenlabs.mjs`, `scripts/build-edl-review.mjs`,
`scripts/validate-beat-sync.mjs` ada di `third_party/herk-edit-kit/`.
Skill ini butuh transkrip tingkat kata: pakai `POST /api/media/{id}/transcribe`
ACEVIDS (faster-whisper) lalu `GET …/transcript?format=json`, atau ElevenLabs Scribe.
