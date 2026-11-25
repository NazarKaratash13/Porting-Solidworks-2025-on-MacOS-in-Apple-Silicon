# План разработки без Wine: от воспроизводимости к CAD

**Цель**: постепенно реализовать собственный исполняющий слой для выбранных
Windows x86-64 программ с AOT ARM64 и native macOS services. Это не обещание
совместимости с SOLIDWORKS или превосходства над Wine/виртуализацией.

## M0 — подтверждённый baseline (первое обязательное действие на Mac)

Задачи: `bootstrap_macos.sh --setup-only`; `tools/dev.py check`;
`tools/dev.py snapshot`; `tools/dev.py smoke` (Plink `-V` без Wine), затем
`tools/dev.py native-full`. Сохранить JSON snapshot, логи, хэши входов и
ревизию Git. Базовый smoke тест PASS только при статусе `0` и строке
`plink: Release 0.83`.

**Сейчас**: подготовлена инфраструктура и пройдены переносимые тесты Linux,
не подтверждено на пользовательском M4. Это **open gate**, а не завершение M0.

## M1 — слой воспроизводимой диагностики и ABI

1. Описать guest↔host ABI: параметрические типы, Win64 calling convention,
   сохранение регистров, SEH/TLS, reentrant callbacks, last-error.
2. Добавить минимальные фикстуры на границах ABI (integer/pointer arguments,
   callbacks, Unicode, alignment, error propagation, рекурсия).
3. Использовать `tools/pe_inventory.py` и `recompiler/audit_pe.py` для каждого
   нового PE: отчёт об импортах + блокирующей инструкции.
4. Выделять host-service API из `console_runtime.c` **маленькими патчами**,
   без переписывания всего runtime.

**PASS**: каждый тест сверяет выход, ошибки и callback behavior; нет фиктивных
успешных ответов для неподдерживаемых API.

## M2 — первый независимый GUI/USER32 прототип

Начать с собственного тестового Windows x64 PE (исходник теста под нашим
контролем): `RegisterClassExW` → `CreateWindowExW` → `ShowWindow` →
`GetMessageW` / `TranslateMessage` / `DispatchMessageW` → `WM_PAINT` / `WM_DESTROY`
→ `PostQuitMessage`. Сохранять окно и message queue на native стороне, например
в тонком слое AppKit. Соответствие Windows handles, UTF-16 strings, window
procedures и callback ABI обязательно.

**PASS**: реальное окно создаётся и закрывается на Mac **без Wine, Rosetta,
wineserver и запуска x86-кода через Wine**; GUI screenshot и event log с
контрольными callback-событиями. Сам факт открытия окна недостаточен.

## M3 — расширение системного слоя

Memory mapping/permissions, API-set resolution, loader/forwarded exports,
Registry, threading, asynchronous I/O, sockets, filesystem semantics, faults,
resources, COM activation/marshalling, OLE, .NET при необходимости. Каждая
группа API получает независимый набор PE fixtures и негативные тесты.

**PASS**: проверяемый образец GUI-приложения с файлами/потоками/ресурсами
работает без Wine; unsupported flows дают диагностику, а не молчаливое
«успешно».

## M4 — графика и масштабируемость

Сначала GDI/системные ресурсы, затем нужные конкретному приложению OpenGL/WGL,
DXGI/Direct3D, GPU synchronization, шрифты и отображение. Для CAD необходимы
точность вычислений, большие рабочие наборы, кеширование IR/объектов,
инкрементальная компиляция и измерения peak RSS/latency.

**PASS**: функциональные графические fixtures и количественные измерения,
без экстраполяции результатов Plink.

## M5 — оценка конкретного SOLIDWORKS

При наличии законно полученной тестовой версии: инвентаризация PE/DLL,
зависимости COM/.NET/MSVC runtime, GPU/OpenGL, сервисы лицензирования,
различные процессы и драйверы. Делать вывод о реализуемости по **цепочке
блокеров** и независимым прототипам. Не пытаться заменять тысячи Windows API
заглушками без реализации семантики.

## Первые задачи после M0

| ID | Приоритет | Задача | Проверяемый результат |
|---|---|---|---|
| DEV-001 | P0 | Зафиксировать baseline на M4 | JSON + PASS `smoke` и отчёт `native-full` |
| DEV-002 | P0 | ABI matrix для host callbacks | 64-bit integer/pointer, UTF-16, stack/callback tests |
| DEV-003 | P0 | Стандартизировать missing API diagnostics | одинаковый идентификатор DLL!Symbol, причина отказа |
| DEV-004 | P1 | Win32 GUI fixture без Wine | исходник + тест callback/event sequence |
| DEV-005 | P1 | Минимальный AppKit adapter | создаваемое окно, корректное закрытие, без Wine |
| DEV-006 | P1 | Регрессии memory/SEH/TLS | границы и ошибки проверяются автоматическими тестами |

Не закрывать задачу только потому, что код компилируется. Для каждой задачи
указывать: входной тест, наблюдаемую семантику, лог и версии инструментов.
