# Архитектура: карта исходников для дальнейшей разработки

Основано на исходниках приложенного проекта (подготовленная версия). Здесь
описаны **реально существующие** узлы и границы; не считать каждый слой готовым
для произвольного Windows-приложения.

## Текущий тракт исполнения

```text
Windows x86-64 PE (.exe/.dll)
       │
       ├─ pefile + разбор PE, импортов, секций и unwind
       │  console_lift.py / lift.py / build_console_modules.py
       ▼
Гостевой x86-64 control-flow + регистры + флаги
       │
       ├─ ConsoleLift -> текст LLVM IR
       ├─ guest indirect calls/returns -> dispatch tables
       └─ не полностью восстановленный код -> runtime interpreter / diagnostic trap
       ▼
Apple Clang / LLVM -> ARM64 Mach-O object / executable / dylib
       │
       ├─ console_runtime.c: адресное пространство гостя, PE-loader,
       │   Win32/CRT shims, TLS, heap, потоки, синхронизация, исключения
       ├─ build_console_modules.py: lift/load DLL и связывание импортов
       └─ runtime / guest DLLs -> вызовы host OS
       │
       ├─ консольные сценарии: автономные macOS нативные shims (частично)
       └─ GUI/network: сейчас Wine-hosted Unix layer (НЕ автономный)
```

## Где менять код

| Функциональная область | Файлы | Контрольные проверки |
|---|---|---|
| Декодирование x86 и LLVM IR | `recompiler/lift.py`, `recompiler/console_lift.py` | `recompiler/run.sh`, `verify.py`, `verify_console.py` |
| Определение PE и первый blocker | `recompiler/audit_pe.py`, `recompiler/console_lift.py` | `tools/pe_inventory.py`, тесты PE |
| PE/DLL загрузчик и таблицы импортов | `recompiler/build_console_modules.py`, `recompiler/console_runtime.c`, `recompiler/translate_console_plugin.py` | `recompiler/fixtures/dynamic_dll` и `ntdll` |
| Windows API, CRT, системные вызовы | `recompiler/console_runtime.c`, `recompiler/apis.json`, `recompiler/generate_shims.py`, `recompiler/generated_shims.h` | console fixtures, `crt` (часть опциональна) |
| x86 fallback и исполнения по непрямым переходам | `recompiler/x86_interpret.h`, `recompiler/x86_bridge.c` | `fixtures/jit`, `fixtures/vm_fault` |
| Хостинг графики (текущий путь) | `recompiler/wine-host/*`, `recompiler/fixtures/gui` | hosted tests, **только при наличии Wine** |
| Параметры инструментов и повторяемость | `tools/doctor.py`, `tools/dev.py`, `tools/pe_inventory.py` | `python3 tools/dev.py check` |

## Архитектурный выбор для цели «без Wine»

Нельзя считать «AOT x86→ARM64» заменой Win32: это разные задачи. Даже если весь
машинный код перекомпилируется, приложению требуются файловые дескрипторы,
регистры, адресация памяти, системный loader, thread model, USER32/GDI,
COM/OLE, окна, сообщения, а CAD — ещё и GPU-стек (для SOLIDWORKS особенно
существенны OpenGL/WGL и поддержка драйверов).

На этапе M1 требуется построить **собственный интерфейс host services**:
`guest API name/ordinal + raw guest args -> validated native handler -> guest
result + Windows error/status`. GUI-адаптер должен существовать **в отдельном
модуле** и не зависеть от загрузки Wine-host компонентов. Для окон на macOS
можно исследовать мост через AppKit, но сама механика class registry, handles,
window procedures, событий/очередей и синхронизации требует реализации и
проверки на ARM64.

Приоритет: сначала проверяемая семантика небольшой подсистемы, затем покрытие
новых API. Автоматическая генерация тысяч заглушек до появления ABI/семантики
невозможна как критерий успеха.

## Известные границы и риски

- `console_lift.py` и `console_runtime.c` — большие связанные файлы: изменение
  одного часто влияет на runtime ABI; нужен тест до и после правки.
- `.pdata`, SEH/TLS, обработка faults, ASLR и guest identity mapping накладывают
  ограничение на адреса гостя и защиту страниц.
- Компилятор принимает LLVM IR из перекомпилятора, но LLVM IR не является
  полным переносимым представлением Win32/COM/GUI.
- Режим `--trace` НЕ гарантирует, что непереведённый код запустится: может
  остановиться на достижении блока, в зависимости от пути исполнения.
- Hosted GUI/SSH — реальный результат автора исходного проекта, но зависимости
  Wine (`wineserver`/Unix layer) нельзя скрывать в критериях M2.
