# 自定义词汇插图恢复流程

主仓库只保存代码、模板和声明式数据。自定义图片、Voicepeak 语音和绘图源文件放在独立的 `source/` 仓库里，不随主仓库同步。

## 需要的仓库

主仓库：

```powershell
git clone https://github.com/CasseShimada/anki-jlpt-decks.git
cd anki-jlpt-decks
git checkout develop
```

媒体仓库必须克隆到主仓库根目录的 `source/`：

```powershell
git clone -b develop https://github.com/nitavhxvakyealg/nihongo-vocab-illustrations.git source
```

`source/` 是独立 Git 仓库。`.clip` 文件只放到 `C:\Users\Admin\OneDrive - MSFT\!!FINISHEDWORK\日语插图`，不要提交。

## 数据真相源

`deck-source/vocab-customizations.tsv` 保存每条自定义的恢复信息：

- `VocabKanji`: 目标词，按 `notes.csv` 的 `VocabKanji` 精确匹配。
- `ImageFile`: 写入 Anki 媒体库的稳定图片文件名。
- `SourceFile`: `source/` 根目录里的原始图片文件名。
- `Action`: `insert`、`reuse-slot`、`replace-slot` 或 `image-only`。
- `Slot`: 插入、替换或沿用的原始例句槽位。
- `SentKanji`、`SentFurigana`、`SentDefSC`、`SentDefTC`: 要写入 Anki 的例句内容。
- `AudioFile`: `source/` 根目录里的语音文件名，同时也是写入 Anki 媒体库的文件名。

`notes.csv` 保持 `main` 的原版内容；脚本运行时以它作为基础卡组，再按 TSV 生成中间结果。

## 应用到 Anki

先导入原版卡组，打开 Anki 并启用 AnkiConnect：

```text
http://127.0.0.1:8765
```

检查所有媒体和字段映射：

```powershell
python scripts\sync_vocab_customizations_to_anki.py --dry-run
```

只检查一个词：

```powershell
python scripts\sync_vocab_customizations_to_anki.py --dry-run --word 提出
```

正式写入 Anki：

```powershell
python scripts\sync_vocab_customizations_to_anki.py
```

脚本会：

1. 要求 `source/` 存在。
2. 从 TSV 读取例句、图片、语音和槽位规则。
3. 把引用到的媒体复制到 `tmp/vocab-customizations-media/`。
4. 生成 `tmp/vocab-customizations-plan.json`。
5. 通过 AnkiConnect 上传媒体、更新模板和样式、写入 note 字段。

`tmp/`、`source/` 和自定义媒体文件不会进入主仓库提交。
