#!/usr/bin/env python3
"""Apply declarative vocab illustration/example customizations to Anki.

The tracked deck source stays as the upstream/base deck. Custom examples,
media names, and slot placement rules live in deck-source/vocab-customizations.tsv.
Media files themselves live in the external source/ repository and are copied to
tmp/ before being uploaded to AnkiConnect.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MODEL_NAME = "eggrolls-JLPT10k-v3.5"
ANKI_URL = "http://127.0.0.1:8765"
CUSTOMIZATIONS_PATH = Path("deck-source/vocab-customizations.tsv")
NOTES_PATH = Path("deck-source/notes.csv")
SOURCE_DIR = Path("source")
TMP_MEDIA_DIR = Path("tmp/vocab-customizations-media")
PLAN_OUTPUT_PATH = Path("tmp/vocab-customizations-plan.json")

SLOT_INDEXES = {
    1: {"type": 11, "kanji": 12, "furigana": 13, "sc": 14, "tc": 15, "audio": 16},
    2: {"type": 17, "kanji": 18, "furigana": 19, "sc": 20, "tc": 21, "audio": 22},
    3: {"type": 23, "kanji": 24, "furigana": 25, "sc": 26, "tc": 27, "audio": 28},
    4: {"type": 29, "kanji": 30, "furigana": 31, "sc": 32, "tc": 33, "audio": 34},
}

TEMPLATE_NAMES = ["日-中", "中-日"]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


@dataclass
class SlotData:
    type: str = ""
    kanji: str = ""
    furigana: str = ""
    sc: str = ""
    tc: str = ""
    audio: str = ""

    def is_empty(self) -> bool:
        return not any([self.type, self.kanji, self.furigana, self.sc, self.tc, self.audio])

    def to_fields(self, slot: int) -> dict[str, str]:
        return {
            f"SentType{slot}": self.type,
            f"SentKanji{slot}": self.kanji,
            f"SentFurigana{slot}": self.furigana,
            f"SentDefSC{slot}": self.sc,
            f"SentDefTC{slot}": self.tc,
            f"SentAudio{slot}": self.audio,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply vocab customization TSV to Anki.")
    parser.add_argument("--customizations", default=str(CUSTOMIZATIONS_PATH))
    parser.add_argument("--notes", default=str(NOTES_PATH))
    parser.add_argument("--source-dir", default=str(SOURCE_DIR))
    parser.add_argument("--tmp-media-dir", default=str(TMP_MEDIA_DIR))
    parser.add_argument("--plan-output", default=str(PLAN_OUTPUT_PATH))
    parser.add_argument("--model-name", default=MODEL_NAME)
    parser.add_argument("--anki-url", default=ANKI_URL)
    parser.add_argument("--word", action="append", help="Apply only the given VocabKanji. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Build the plan but do not call AnkiConnect.")
    parser.add_argument("--skip-templates", action="store_true", help="Do not update Anki model templates/style.")
    return parser.parse_args()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file, delimiter="\t"))


def read_notes(path: Path) -> dict[str, list[list[str]]]:
    notes: dict[str, list[list[str]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) > 3:
            notes.setdefault(cols[3], []).append(cols)
    return notes


def slot_from_row(row: list[str], slot: int) -> SlotData:
    idx = SLOT_INDEXES[slot]
    return SlotData(
        type=row[idx["type"]],
        kanji=row[idx["kanji"]],
        furigana=row[idx["furigana"]],
        sc=row[idx["sc"]],
        tc=row[idx["tc"]],
        audio=row[idx["audio"]],
    )


def custom_slot(record: dict[str, str]) -> SlotData:
    audio_file = record.get("AudioFile", "").strip()
    return SlotData(
        type=record.get("SentType", "").strip(),
        kanji=record.get("SentKanji", "").strip(),
        furigana=record.get("SentFurigana", "").strip(),
        sc=record.get("SentDefSC", "").strip(),
        tc=record.get("SentDefTC", "").strip(),
        audio=f"[sound:{audio_file}]" if audio_file else "",
    )


def parse_slot(value: str, *, required: bool = False) -> int | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise RuntimeError("Missing slot number")
        return None
    slot = int(value)
    if slot not in SLOT_INDEXES:
        raise RuntimeError(f"Invalid slot number: {slot}")
    return slot


def build_slots(base_row: list[str], record: dict[str, str]) -> list[SlotData]:
    if len(base_row) != 39:
        raise RuntimeError(f"{record.get('VocabKanji', '')}: base row has {len(base_row)} columns; expected 39")
    base = [slot_from_row(base_row, slot) for slot in range(1, 5)]
    action = (record.get("Action") or "insert").strip().lower()
    slot = parse_slot(record.get("Slot", ""), required=action in {"insert", "replace-slot", "reuse-slot"})

    if action == "image-only":
        return base

    if action == "reuse-slot":
        assert slot is not None
        selected = custom_slot(record)
        if selected.is_empty():
            raise RuntimeError(f"{record.get('VocabKanji', '')}: reuse-slot must store the reused example fields")
        remaining = [item for index, item in enumerate(base, start=1) if index != slot]
        return ([selected] + remaining)[:4]

    inserted = custom_slot(record)
    if inserted.is_empty():
        raise RuntimeError(f"{record.get('VocabKanji', '')}: custom slot is empty")

    if action == "insert":
        assert slot is not None
        result = base[:]
        result.insert(slot - 1, inserted)
        return result[:4]

    if action == "replace-slot":
        assert slot is not None
        remaining = [item for index, item in enumerate(base, start=1) if index != slot]
        return ([inserted] + remaining)[:4]

    raise RuntimeError(f"{record.get('VocabKanji', '')}: unknown Action {action!r}")


def fields_for_slots(slots: list[SlotData]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for slot_number, slot in enumerate(slots, start=1):
        fields.update(slot.to_fields(slot_number))
    return fields


def anki_request(anki_url: str, action: str, params: dict[str, Any] | None = None) -> Any:
    payload = json.dumps({"version": 6, "action": action, "params": params or {}}).encode("utf-8")
    request = urllib.request.Request(
        anki_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AnkiConnect request failed for {action}: {exc}") from exc
    if data.get("error"):
        raise RuntimeError(f"{action}: {data['error']}")
    return data.get("result")


def copy_media(source_dir: Path, tmp_media_dir: Path, source_name: str, media_name: str) -> Path:
    if not source_dir.exists():
        raise RuntimeError(f"Missing external media directory: {source_dir}")
    source_path = source_dir / source_name
    if not source_path.exists():
        raise RuntimeError(f"Missing external media file: {source_path}")
    tmp_media_dir.mkdir(parents=True, exist_ok=True)
    destination = tmp_media_dir / media_name
    shutil.copyfile(source_path, destination)
    return destination


def prepare_media(record: dict[str, str], source_dir: Path, tmp_media_dir: Path) -> dict[str, str]:
    image_name = record["ImageFile"].strip()
    source_name = (record.get("SourceFile") or image_name).strip()
    image_path = copy_media(source_dir, tmp_media_dir, source_name, image_name)
    media = {"image": str(image_path)}

    audio_name = (record.get("AudioFile") or "").strip()
    if audio_name:
        audio_path = copy_media(source_dir, tmp_media_dir, audio_name, audio_name)
        media["audio"] = str(audio_path)
    return media


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def patch_front(front: str, records: list[dict[str, str]]) -> str:
    lines = [
        f"      '{record['VocabKanji']}': '{record['ImageFile']}',"
        for record in records
        if record.get("VocabKanji") and record.get("ImageFile")
    ]
    marker = "const hintImages = {"
    if marker not in front:
        raise RuntimeError("setupVocabHint mapping not found in front template")
    start = front.index(marker) + len(marker)
    brace_depth = 1
    end = start
    while end < len(front):
        if front[end] == "{":
            brace_depth += 1
        elif front[end] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        end += 1
    if end >= len(front):
        raise RuntimeError("Could not find hintImages closing brace")
    body = "\n" + "\n".join(lines) + "\n    "
    return front[:start] + body + front[end:]


def write_plan(path: Path, applied: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"applied": applied}, ensure_ascii=False, indent=2), encoding="utf-8")


def update_templates(anki_url: str, model_name: str, records: list[dict[str, str]]) -> dict[str, Any]:
    template_dir = Path("deck-source/templates")
    templates = anki_request(anki_url, "modelTemplates", {"modelName": model_name})
    for name in TEMPLATE_NAMES:
        front_path = template_dir / f"{model_name}-{name}-front.html"
        back_path = template_dir / f"{model_name}-{name}-back.html"
        if name in templates and front_path.exists():
            templates[name]["Front"] = patch_front(read_text(front_path), records)
        if name in templates and back_path.exists():
            templates[name]["Back"] = read_text(back_path)
    anki_request(anki_url, "updateModelTemplates", {"model": {"name": model_name, "templates": templates}})

    styles_path = template_dir / f"{model_name}-styles.css"
    styles_updated = False
    if styles_path.exists():
        css = read_text(styles_path)
        anki_request(anki_url, "updateModelStyling", {"model": {"name": model_name, "css": css}})
        styles_updated = True
    return {"templates": TEMPLATE_NAMES, "stylesUpdated": styles_updated}


def update_note(anki_url: str, record: dict[str, str], slots: list[SlotData]) -> int:
    word = record["VocabKanji"]
    ids = anki_request(anki_url, "findNotes", {"query": f"VocabKanji:{word}"})
    if len(ids) != 1:
        raise RuntimeError(f"Expected one Anki note for {word}, found {len(ids)}")
    fields = fields_for_slots(slots)
    anki_request(anki_url, "updateNoteFields", {"note": {"id": ids[0], "fields": fields}})
    return int(ids[0])


def apply_record(
    record: dict[str, str],
    notes: dict[str, list[list[str]]],
    source_dir: Path,
    tmp_media_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    word = record["VocabKanji"]
    if word not in notes:
        raise RuntimeError(f"Missing base note row for {word}")
    if len(notes[word]) != 1:
        raise RuntimeError(f"Expected one base note row for {word}, found {len(notes[word])}")
    slots = build_slots(notes[word][0], record)
    media_paths = prepare_media(record, source_dir, tmp_media_dir)
    fields = fields_for_slots(slots)

    result: dict[str, Any] = {
        "word": word,
        "imageFile": record["ImageFile"],
        "action": record.get("Action", ""),
        "slot": record.get("Slot", ""),
        "mediaPaths": media_paths,
        "fields": fields,
        "sentKanji1": slots[0].kanji,
    }
    if args.dry_run:
        return result

    anki_request(args.anki_url, "storeMediaFile", {"filename": record["ImageFile"], "path": media_paths["image"]})
    audio_file = (record.get("AudioFile") or "").strip()
    if audio_file:
        anki_request(args.anki_url, "storeMediaFile", {"filename": audio_file, "path": media_paths["audio"]})
    result["noteId"] = update_note(args.anki_url, record, slots)
    return result


def main() -> int:
    args = parse_args()
    all_records = read_tsv(Path(args.customizations))
    records = all_records
    if args.word:
        wanted = set(args.word)
        records = [record for record in all_records if record.get("VocabKanji") in wanted]

    notes = read_notes(Path(args.notes))
    source_dir = Path(args.source_dir)
    tmp_media_dir = Path(args.tmp_media_dir)

    applied = [apply_record(record, notes, source_dir, tmp_media_dir, args) for record in records]
    write_plan(Path(args.plan_output), applied)
    template_result = None
    if not args.dry_run and not args.skip_templates:
        template_result = update_templates(args.anki_url, args.model_name, all_records)

    print(json.dumps({"applied": applied, "templates": template_result, "planOutput": args.plan_output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
