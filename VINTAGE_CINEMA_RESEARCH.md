# Vintage Cinema · Style contract (22 November 2026)

## User references
- Supplied autumn object moodboard: cozy editorial vintage (brown, cream, wool, coffee, foliage)
- Supplied 53.6-second screen recording (2026-11-22 20:41): Pinterest browsing for vintage video inserts, showing paper textures, retro TV, 8/16/35mm perforated film, film projector, CRT/noise, film frame, clapper, vintage cinema cards and old-photo transitions
- Private user-uploaded cutouts: watches, keys, aged letters, porcelain, vinyl record, candles, film ticket, antique lamps, frames and books

These are different layers. Autumn props are not universal vintage stickers for every spoken subject.

## Actual selection and render
- iPad editor: choose "🎞️ Винтажное кино". It sets caption_variant=vintage, video_filter=vintage, insert_style=vintage, insert_sound=on, subtitle_sfx=typewriter
- Existing Cloudflare v4 settings already allow vintage; no Worker changes required
- Base footage: warm aged colors, true time-varying grain and vignette before captions, retaining original audio
- Intro: first 4 seconds no visual inserts; full-frame vintage cutaways start no earlier than 5.2s
- Vintage full-screen visuals: 1.55–2.2s, dark film-gate and worn-paper variants, film sprocket holes, scratches, restrained serif lettering quoted only from approved speech; fades in and out
- Speech-matched private PNG stickers (only if the user imports the private ZIP). They use person masks, stay small, avoid subtitle regions, and skip if no safe free space
- All audio: original dialogue unchanged. Quiet original film-projector sound design on vintage cutaways; user-uploaded typewriter WAV or built-in procedural typing on captions. No noisy trailer whooshes automatically
- Semantic scenes, small object overlays, caption motion, film color and sound can coexist within the same vintage preset. No need to select one decorative technique exclusively

## Curated public sources examined
- Pinterest newsroom: https://newsroom.pinterest.com/news/2026-pinterest-hobbies-trend-report/ (scrapbook/archival/vintage aesthetics)
- Mixkit projector SFX examples: https://mixkit.co/free-sound-effects/movie-projector/
- Pixabay small projector sound: https://pixabay.com/sound-effects/technology-small-film-projector-26188/
- Pixabay 8mm film sound: https://pixabay.com/sound-effects/technology-008222-8mm-film-projector-61319/
- Freesound film-projector recording (CC BY, attribution required): https://freesound.org/people/Metzik/sounds/393408/
- Mixkit old film stock clips: https://mixkit.co/free-stock-video/old-film/
- Mixkit Sound Effects Free License: https://mixkit.co/license/modal/sfxFree/
- Pexels license: https://www.pexels.com/legal-pages/license/

## Licensing / asset provenance
Pinterest is a visual reference, not a license. Do not scrape or redistribute creator images from Pinterest. Mixkit's SFX free license permits use inside finished videos but prohibits redistributing raw assets inside a tool, stock pack or template. Pexels prohibits standalone redistribution. These stock files have not been copied into the public repo. Audio currently integrated in Vintage Cinema is self-produced programmatically, not a licensed third-party sample. The private ZIP is made from user-provided images; it is not public-domain certified and is not to be committed to public GitHub.

## Expansion for other aesthetic sets
Use distinct contracts per style:
1. Visual language / typography / palette
2. Per-speech semantic cue trigger rules
3. Short cinematic full-frame transitions
4. Small person-safe sticker library (private rights-cleared PNG)
5. Sound identity with verified license
6. Preview representative of final render and intro-protection tests

No generic all-styles-use-random-emoji engine. When the user sends another aesthetic, create a separate named package and retain the shared speech-safe compositor.
