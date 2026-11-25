# Рабочий процесс разработки (macOS Apple Silicon)

Проект подготовлен для **разработки**, а не только для установки. В архиве
находится локальный Git-репозиторий с исходным baseline и отдельным коммитом
инструментов разработки. Его можно открыть в VS Code/Cursor/другом редакторе.

## 0. Начать работу

```bash
cd arm64-recompiler-dev
# Два сохранённых коммита: импорт подготовленной версии и dev-инфраструктура
git log --oneline -2
git status

# На любой ОС, БЕЗ зависимостей и сети: синтаксис + unit tests
python3 tools/dev.py check

# Статические импорты трёх PE без Wine и без pip
python3 tools/pe_inventory.py work/corpus --output work/reports/corpus-imports.json
```

## 1. Воспроизводимая разработка на M4

```bash
xcode-select --install  # только если Xcode Command Line Tools не установлены
bash tools/bootstrap_macos.sh --setup-only

# Выполнять через Python из venv, чтобы использовать закреплённые зависимости
work/venv/bin/python3 tools/dev.py check
work/venv/bin/python3 tools/dev.py snapshot
work/venv/bin/python3 tools/dev.py smoke

# Полный native набор после первой удачной сборки
work/venv/bin/python3 tools/dev.py native-full
```

Артефакты snapshot и inventory сохраняются в `work/reports/` и игнорируются
Git. Инструменты запускают именно локальные EXE. `native-full` может содержать
опциональные fixtures, которые печатают `SKIP`; проверять лог, а не только код
завершения. Для GUI без Wine пока не существует PASS-gate.

## 2. Запуск независимых проверок

- `python3 tools/dev.py check`: переносимая синтаксическая проверка всех `.py`
  и `.sh`, плюс unit tests (включая собственный парсер PE).
- `python3 tools/dev.py unit`: только unit tests.
- `python3 tools/dev.py snapshot`: сведения об ОС, версиях Python/инструментов,
  Git SHA/dirty, дайджесте исходников, хэши корпуса и установленных пакетах.
- `python3 tools/dev.py smoke`: запуск независимого Plink `-V` только на macOS
  ARM64 с обязательной проверкой зависимостей. Не ставит Wine.
- `python3 tools/dev.py native-full`: исходный `recompiler/run.sh`, только Mac.
- `python3 tools/pe_inventory.py /path/to/app.exe`: статический список импортов,
  включая delay imports; импорт `Foo` не доказывает, что shim совместим.
- `python3 recompiler/audit_pe.py path/to/app.exe`: следующий этап после
  установки `pefile`, определяет первый blocker lifter для конкретного PE.

## 3. Правила маленьких итераций

1. Перед модификацией: `git status` и `python3 tools/dev.py snapshot`.
2. Описать фиксируемое поведение и написать *падающий* тест/fixture.
3. Менять минимальный конкретный слой (см. `ARCHITECTURE_RU.md`).
4. `tools/dev.py check` + соответствующий native gate на Mac.
5. Сравнить с baseline, зафиксировать `git diff` и `git commit`.
6. Не смешивать оптимизацию производительности с функциональной правкой.

## 4. Git и GitHub Actions

`main` содержит два базовых коммита; новые эксперименты делать в ветке,
например `git switch -c feature/native-user32`. Запуск Actions доступен после
публикации **своего** репозитория на GitHub; никаких удалённых репозиториев или
секретов в данном архиве нет.

`.github/workflows/quality.yml` запускает переносимые проверки на Ubuntu при
каждом push/PR. Native macOS ARM64 smoke включается *вручную*
(`workflow_dispatch`) для экономии ресурсов. Никакой Wine CI не устанавливает.
Работоспособность workflow на GitHub здесь **не проверялась**.

## 5. Ограничения и безопасность

- Инструментарий не гарантирует запуск произвольного Windows PE и не заменяет
  лицензирование/установку Windows-приложений.
- `work/corpus/*.exe` из пользовательского архива не имеют независимо
  подтверждённого происхождения; запускать неизвестные бинарники с минимальными
  правами и без чувствительных данных.
- `snapshot` сохраняет локальные пути и версии инструментов. Перед публикацией
  отчётов проверить наличие приватных путей.
- Wine-hosted остаётся опциональным контрольным режимом, **не** частью цели
  независимого GUI.
