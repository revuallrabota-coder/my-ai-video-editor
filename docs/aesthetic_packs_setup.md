# Reels private aesthetic asset packs: Old Money / Burgundy / Pink Tender

Three SEPARATE packs. The choice of a preset controls semantics, illustrated fallback, movement and sound. Public GitHub contains only source links and original generated code; it does not ship third-party clips or stock sound recordings.

## Private server installation (no iPad local files required)
On the actual FFmpeg renderer (not Cloudflare Worker), set an environment variable `PRIVATE_STYLE_ASSETS_DIR` to an existing **private** directory that contains licensed, reviewed assets:
```text
PRIVATE_STYLE_ASSETS_DIR=/opt/ai-reels-assets

/opt/ai-reels-assets/
├── old_money/
│   ├── book.mp4
│   ├── book.wav
│   ├── coffee.mp4
│   ├── phone.mp4
│   ├── phone.wav
│   ├── typewriter.mp4
│   ├── typewriter.wav
│   ├── documents.mp4
│   ├── documents.wav
│   ├── keyhole.mp4
│   ├── keyhole.wav
│   ├── door.mp4
│   └── door.wav
├── burgundy/
│   ├── silk.mp4
│   ├── silk.wav
│   ├── bow.mp4
│   ├── bow.wav
│   ├── flower.mp4
│   ├── flower.wav
│   ├── seal.mp4
│   ├── seal.wav
│   ├── letter.mp4
│   └── letter.wav
└── pink_tender/
    ├── silk.mp4
    ├── silk.wav
    ├── flower.mp4
    ├── flower.wav
    ├── bow.mp4
    ├── bow.wav
    ├── pearl.mp4
    └── pearl.wav
```
Each semantic theme may contain an MP4, a WAV, both or neither. No downloaded user/Pinterest images are used by default. The engine discovers only exact sanitized `theme.mp4` and `theme.wav` under its own style, and falls back to original PIL vector artwork and quiet style-specific synthesized audio. If a clip is present it is used as a short FULL-SCREEN speech-matched cutaway, and its audio is deliberately discarded to protect the speaker's original voice. Each selected clip duration is short (approximately 1.35–1.65 s), with fade-in/out. Their assets and sound files are not interchangeable between styles.

**Do not publish this private directory in GitHub or expose as a download.** The installer must store URL, author, original filename, obtained license/version and rights check date separately for each material, verify actual clip format, video and audio stream, and review social media commercial permission. User-provided Pinterest screenshots are references only, not directly licensed assets.

## Motion profiles
- Old Money: small serif archival card and slow upward drift; soft paper/watch/typewriter/vinyl sounds. Real video: antique scene, coffee or paper cutaway
- Burgundy: deep wine satin/rose/wax seal icon, silk glide transition, fabric/rustle/wax/glass cues
- Pink Tender: blush silky, bows/pearls/flowers, airy two-axis floating dissolve, feather-light air/chime/petal sounds

## Sources by style
- Old Money: [catalog](old_money_asset_sources.md)
- Burgundy: [catalog](burgundy_asset_sources.md)
- Pink: [catalog](pink_tender_asset_sources.md)
- Vintage Cinema: [catalog](vintage_asset_sources.md)

## iPad deployment
The Mini App is served from GitHub Pages and should update with published `main`. The Cloudflare Worker is independent and MUST be manually redeployed from `cloudflare_launcher_ipad.txt` (or identical `cloudflare_launcher.js`). Worker `/health` must show **style_contract_version = 6**. The frontend checks v6 and confirms the accepted `insert_style` before uploading media. This prevents outdated Workers from silently substituting an old template.

Code is in `aesthetic_fx.py`, `old_money_fx.py`, `retro_inserts.py`, `reels_effects.py`, `index.html`, `cloudflare_launcher.js`. `test_aesthetic_packs.py` contains regression checks.

**Status:** source/catalogue and Python/UI/Worker changes are committed, but no stock media binaries were installed on the private renderer and no end-to-end Telegram export was verified in this session. Real footage won't appear until files exist in private storage.
