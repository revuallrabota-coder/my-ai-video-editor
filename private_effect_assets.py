"""Opt-in, PRIVATE use of the user's uploaded icon and sound ZIP packs.

Archives are not committed to the repository and are never served publicly.
Only safe, relevant pre-rendered QuickTime icon MOVs and optional WAV samples
are opened. Adobe .mogrt and .ffx project presets are not FFmpeg media files.
They are *not* executed and no Adobe application is required.
"""
from __future__ import annotations

from dataclasses import dataclass,field
from pathlib import Path
from typing import Sequence
from zipfile import ZipFile,is_zipfile

from semantic_editing import ICON_NAME

MAX_ARCHIVES=4
MAX_ARCHIVE_BYTES=100_000_000
MAX_EXTRACT_BYTES=105_000_000
MAX_FILE_BYTES=18_000_000

OPTIONAL_SOUNDS={"error":"0026_slam 4.wav", "compare":"0026_sweeping slam 1.wav"}
# Flexible names for user-owned effects, including Russian and English WAVs.
# Only these broad categories have deterministic timing in the Reels timeline.
SOUND_KEYWORDS={
    "typewriter":("typewriter","typing","keyboard","typewriter","печать",
                  "печатн","клавиат","машинк"),
    "whoosh":("whoosh","swoosh","sweep","swish","transition","переход",
              "пролёт","пролет","вжух"),
    "pop":("pop","bubble","click","tick","щелч","хлоп"),
}
ALLOWED_EXT={".mov",".wav"}


@dataclass
class PrivateAssets:
    icons: dict[str,Path]=field(default_factory=dict)
    sounds: dict[str,Path]=field(default_factory=dict)
    ignored_adobe_presets: int=0
    selected_files: int=0


def prepare_private_effect_assets(
    archives: Sequence[Path], directory: Path,
) -> PrivateAssets:
    result=PrivateAssets()
    if not archives:
        return result
    if len(archives)>MAX_ARCHIVES:
        raise ValueError("Можно прикрепить максимум четыре ZIP-пакета.")
    total=sum(path.stat().st_size for path in archives)
    if total>MAX_ARCHIVE_BYTES:
        raise ValueError("Размер ZIP-пакетов не должен превышать 100 МБ.")
    directory.mkdir(parents=True,exist_ok=True)
    required_icons=set(ICON_NAME.values())
    required_sounds=set(OPTIONAL_SOUNDS.values())
    remaining=MAX_EXTRACT_BYTES
    for archive in archives:
        if not archive.is_file() or archive.suffix.lower()!=".zip" or not is_zipfile(archive):
            raise ValueError("Неправильный ZIP-пакет анимированных вставок.")
        with ZipFile(archive) as z:
            if len(z.infolist())>1000:
                raise ValueError("Слишком много файлов в ZIP-пакете.")
            for member in z.infolist():
                if member.is_dir() or member.filename.startswith("__MACOSX/"):
                    continue
                filename=Path(member.filename).name
                if filename.endswith((".ffx",".mogrt",".aep")):
                    result.ignored_adobe_presets+=1
                    continue
                sound_kind=next(
                    (kind for kind,words in SOUND_KEYWORDS.items()
                     if filename.lower().endswith(".wav") and any(
                         token in filename.casefold() for token in words)),
                    None
                )
                if (filename not in required_icons and
                    filename not in required_sounds and not sound_kind):
                    continue
                if member.file_size>MAX_FILE_BYTES or member.file_size>remaining:
                    continue
                if member.compress_size<128 or member.file_size>member.compress_size*500:
                    continue
                # Do not extract archive paths; use canonical generated basename.
                dest=directory/(("icon_" if filename in required_icons else "sound_")+
                                filename.replace(" ","_"))
                if dest.is_file():
                    continue
                with z.open(member) as stream, dest.open("wb") as output:
                    import shutil
                    shutil.copyfileobj(stream,output,length=1024*1024)
                if dest.stat().st_size!=member.file_size:
                    dest.unlink(missing_ok=True)
                    continue
                remaining-=member.file_size
                result.selected_files+=1
                for kind,name in ICON_NAME.items():
                    if name==filename:
                        result.icons[kind]=dest
                for kind,name in OPTIONAL_SOUNDS.items():
                    if name==filename:
                        result.sounds[kind]=dest
                if sound_kind and sound_kind not in result.sounds:
                    result.sounds[sound_kind]=dest
    return result
