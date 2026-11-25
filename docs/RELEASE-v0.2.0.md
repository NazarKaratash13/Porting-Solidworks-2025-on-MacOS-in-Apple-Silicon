Техническое превью SOLIDWORKS V3 для Mac с Apple Silicon. Лаунчер позволяет выбрать совместимый Wine, запустить официальный установщик SOLIDWORKS 2025 и собрать локальное приложение с иконкой, Finder Quick Look и собственной копией Wine.

### Файлы

- **SOLIDWORKS-V3-Launcher-macOS-arm64.zip** — лаунчер AppKit для установки и сборки `.app`.
- **SOLIDWORKS-V3-Demo-RU.mp4** — 90 секунд реальной работы, включая вставку третьего болта ISO из Toolbox и повторное открытие сборки.
- **SHA256SUMS.txt** — контрольные суммы файлов релиза.
- **startup.json, operations.csv** — данные замеров на Mac с M4 и 16 ГиБ.

Три запуска дали медиану 27,42 с. Суммарный physical footprint SOLIDWORKS и wineserver вырос с 2,60 до 4,52 ГиБ в серии с 2–11 открытыми документами. [Методика замеров](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon/blob/main/docs/BENCHMARKS_RU.md).

### Требования

Нужны Apple Silicon, macOS 14+, Rosetta, совместимый Wine с исправлениями V3, официальный установщик и действующая лицензия. Штатная активация выполняется в SOLIDWORKS. Лаунчер подписан ad hoc, Apple Developer ID и нотарификация отсутствуют. Упаковку проверили на синтетической установке. Работу SOLIDWORKS проверили на существующей лицензированной установке V3. [Русский README](https://github.com/NazarKaratash13/Porting-Solidworks-2025-on-MacOS-in-Apple-Silicon#readme).
