# Патчи Wine и сведения о сборке

Всё, что отличает рабочий runtime от исходного CrossOver 26.3 / Wine 11, лежит здесь в виде
патчей. Это единственная **версионируемая** копия правок: каталог `work/` в git не попадает,
поэтому собранные `.so`/`.dll` и сам Wine-префикс резервной копией не считаются.

## 1. Исходная точка

| Что | Значение |
|---|---|
| Дистрибутив исходников | `work/solidworks-host/driver-research/crossover-sources-26.3.0.tar.gz` |
| SHA-256 | `ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872` |
| Версия продукта | CrossOver 26.3.0 (Wine 11.0) |
| База Wine | LGPL-2.1-or-later, `sources/wine/LICENSE` |

## 2. Патчи

Порядок чистой сборки находится в [v3.series](v3.series).
Рецепт подготовки и компиляции см. в [руководстве macOS](../MACOS_BUILD.md).

| Файл | Что содержит |
|---|---|
| `winemac.drv-full.patch` | Полный дифф `dlls/winemac.drv` относительно pristine: V3-клип (`gl_clip_region.h`, `window.c`, `opengl.c`, `macdrv.h`, `macdrv_cocoa.h`, `cocoa_window.m`) + исправление `HORZRES/VERTRES` (`gdi.c`) + исправление клипа при resize |
| `winemac-clip-resize.patch` | Изолированная дельта этого этапа: маска строится после применения нового frame и на main thread; `mask.contentsScale` |
| `winemac-clip-fallback.patch` | Дополнительная правка после `winemac.drv-full.patch`. Исправляет объединение вырезов в резервной ветке A. Собрана в отдельной копии, проверка меню SOLIDWORKS впереди. |
| `win32u-solidworks-propertymanager-topmost.patch` | Совместимость `SetWindowPos(HWND_TOPMOST)` для заголовков PropertyManager. Включается `WIN32U_SW_PM_TOPMOST=1` в отдельной V3. [Результаты проверки SOLIDWORKS](../SOLIDWORKS_V3_PROPERTYMANAGER_FIX_RU.md) |
| `wine-solidworks-v3-task-pane-resize.patch` | Оконная правка отдельной тестовой V3. Ограничивает размеры Auto Hider, включает нативный захват края и запрашивает перерисовку при изменении размеров. Применяется поверх текущего дерева V3 с правкой PropertyManager. [Проверка на SOLIDWORKS](../SOLIDWORKS_V3_TASK_PANE_RESIZE_RU.md) |
| `wine-solidworks-v3-task-pane-header.patch` | Очистка освобождённого участка общего GDI-буфера после движения заголовка Task Pane. Применяется поверх `wine-solidworks-v3-task-pane-resize.patch`. |
| `wine-solidworks-v3-task-pane-splitter.patch` | Распространяет очистку на изменение геометрии панели. При реальном сужении разделителем остаточный след воспроизводится. |
| `winemac-solidworks-v3-native-files.patch` | Меню «Файлы Mac», нативные диалоги и события открытия Finder для локальной V3. [Приёмка](../SOLIDWORKS_V3_NATIVE_FILES_RU.md) |
| `wine-solidworks-v3-appkit-save-as.patch` | Перехват штатного Save As и команды в строке меню AppKit. Применяется поверх патча нативных файлов вместе с обновлённым `tools/solidworks-v3-file-bridge.c`. [Приёмка](../SOLIDWORKS_V3_APPKIT_TOOLBOX_RU.md) |
| `wine-solidworks-v3-task-pane-drag-repaint.patch` | Ограниченная перерисовка заголовка Task Pane при завершении внутреннего resize. Применяется поверх патча разделителя. Визуальная приёмка не завершена. |
| `wine-solidworks-v3-appkit-formats.patch` | Формат и режим сохранения в AppKit, обработка мыши нативной панели и штатные команды файловых операций. Применяется поверх `wine-solidworks-v3-appkit-save-as.patch` вместе с обновлённым файловым мостом. |
| `wine-solidworks-v3-pm-redundant-capture.patch` | Убирает лишнее уведомление о потере захвата мыши при повторном захвате той же кнопкой подтверждения PropertyManager. Применяется поверх дерева V3. |
| `wine-solidworks-v3-task-pane-deferred-invalidation.patch` | Запрашивает перерисовку освобождённого участка заголовка после изменения геометрии. Применяется поверх `wine-solidworks-v3-task-pane-drag-repaint.patch`. |
| `wine-solidworks-v3-task-pane-docked-release.patch` | Завершает перерисовку после физического отпускания разделителя MFC и ограничивает рисование заголовка вокруг дочерних кнопок. Применяется поверх `wine-solidworks-v3-appkit-formats.patch` и `wine-solidworks-v3-task-pane-deferred-invalidation.patch`. [Результаты](../SOLIDWORKS_V3_FILE_FORMATS_AND_INPUT_RU.md) |
| `wine-solidworks-v3-appkit-pack-and-go.patch` | Нативный выбор папки и параметров Pack and Go. Применяется поверх патча форматов с обновлённым файловым мостом. |
| `wine-solidworks-v3-task-pane-live-header.patch` | После отпускания разделителя обновляет сам заголовок и его кнопки. Применяется поверх патча завершения перетаскивания. |
| `wine-solidworks-v3-task-pane-tabs.patch` | При закреплённой Task Pane оставляет справа от MDI место для её вкладок. Применяется поверх патча обновления заголовка. [Результаты](../SOLIDWORKS_V3_QUICK_LOOK_TOOLBOX_RU.md) |
| `wine-solidworks-v3-task-pane-caption.patch` | Ограничивает область рисования текста между кнопками заголовка. Применяется поверх патча вкладок. |
| `wine-solidworks-v3-propertymanager-cancel.patch` | Продлевает захват мыши красной кнопки «Вставить компоненты». Применяется поверх патча повторного захвата PropertyManager. |
| `winemac-dock-snapshot-opt-out.patch` | Учитывает `WINEMAC_DISABLE_DOCK_SNAPSHOT=1` до захвата изображения окна для Dock. |
| `wbemprox-full.patch` | `dlls/wbemprox` относительно pristine: вывод `IPEnabled` из фактического MAC (`builtin.c`, `class.c`) + `wbemtrace.h` (инструментирование, использованное при расследовании утечки) |

Старые точечные патчи оставлены для читаемости: `docs/wbemprox-ipenabled.patch`,
`docs/winemac-horzres-retina.patch`.

Применение (из корня дерева Wine):

```sh
patch -p1 < docs/patches/winemac.drv-full.patch
patch -p1 < docs/patches/wbemprox-full.patch
```

### Проверка воспроизводимости исходников (24.11.2026)

Выполнено фактически: pristine-дерево распаковано заново из tarball, патчи применены,
результат сравнён с рабочим деревом.

```
$ git apply --check docs/patches/winemac.drv-full.patch   # ok
$ git apply --check docs/patches/wbemprox-full.patch      # ok
$ diff -ruN <pristine+patches> <work tree>                # пусто
```

Итог: **патч-серия воспроизводит дерево исходников байт-в-байт** (без учёта трёх резервных
файлов `*.before-fix`, `*.fixed`, которые в патч сознательно не включены).

Первая версия `winemac.drv-full.patch` была битой: `grep -v` вырезал заголовки `---/+++` для
резервных файлов, но оставлял их тело, из-за чего в патч попадал фиктивный хунк
`@@ -0,0 +1,2968 @@` и `git apply` падал на `opengl.c` и `window.c`. Патч перегенерирован через
`diff -x '*.before-fix' -x '*.fixed'`.

## 3. Сборка

| Что | Значение |
|---|---|
| Build-каталог | `work/solidworks-host/driver-research/build` |
| Команда | `cd build/dlls/winemac.drv && make` |
| Компилятор | clang (`-arch x86_64 -m64 -O2 -gdwarf-4 -fPIC`) |
| Артефакт | `build/dlls/winemac.drv/winemac.so` |
| Целевое место | `<runtime>/lib/wine/x86_64-unix/winemac.so` |

`wbemprox.dll` собирается целью `dlls/wbemprox` и кладётся в `lib/wine/x86_64-windows/` и
`lib/wine/i386-windows/`.

## 4. Хеши проверенных артефактов (24.11.2026)

Строка для `engine-test` описывает состояние при приёмке. Сейчас этот хеш совпадает с
`winemac.so` в установленном автономном пакете и с резервной копией в
`engine-test/backups/`. Текущий `engine-test` имеет хеш
`87e0090170cb8c6a340a30d4d785b3f0b32996411e587c2ba45140e9c8757870`.
Это отдельная экспериментальная сборка с опцией отключения миниатюры Dock.

| Файл | SHA-256 | Роль |
|---|---|---|
| `engine-test/.../x86_64-unix/winemac.so` | `3bc20821fa6e7aed6d3d16666ce35cb0e4663d9edd979f79e0e2883be4a0d5ed` | проверенный драйвер (V3 + HORZRES + clip-resize) |
| `engine-staging/.../x86_64-unix/winemac.so` | `a46e1c63a5096210626d64ef6c62ddea7632f95dbcf437b1a3bf006d43dcf532` | рабочий движок пользователя, **не изменялся** |
| `engine-test/.../x86_64-windows/wbemprox.dll` | `777fab4504ba6913c3c70243efcebd95f3438fb3929e94f4e7426a886734f1cb` | WMI-исправление |
| `engine-staging/.../x86_64-windows/wbemprox.dll` | `89ffffe5618a56b8bfb60bbb0596e1108572a02546e3d48614d4a16821550bb4` | то же исправление, независимая сборка |
| `engine-test/.../i386-windows/wbemprox.dll` | `c4dd0531a4ff51753c6227c8b44dc438418e0815167e2ca884f1064c57d077a8` | 32-битная копия |

## 5. Воспроизводимость — честный результат

Функционально сборка воспроизводима: те же исходники дают тот же код. **Побитово — нет.**

Три последовательные полные пересборки `winemac.so` из одних и тех же исходников дали три разных
SHA-256. Разбор двух сборок: размер совпадает до байта (592 240), различаются **19 байт**:

* 16 байт по смещению 2913 — поле `LC_UUID` (линкер генерирует случайный UUID при каждой линковке);
* 3 байта в разных местах — метаданные DWARF.

Практический вывод: сверять сборки по хешу между пересборками нельзя. Для релиза фиксируется
хеш **конкретного** поставленного бинарника (таблица выше) плюс патч-серия и рецепт сборки.
Если нужна побитовая воспроизводимость, линковать с `-Wl,-no_uuid` и `-g0`; это не проверялось.

## 6. Чего здесь нет

Патчи не покрывают и не могут покрыть:

* содержимое Wine-префикса (`system.reg`, `user.reg`, установленные MSI, лицензионные файлы);
* проприетарные бинарники SOLIDWORKS;
* проприетарные компоненты CrossOver (см. `docs/RELEASE_PREP_RU.md`, раздел о лицензиях).

Резервная копия префикса — отдельная сущность: `work/solidworks-host/checkpoints/activated-20261122/prefix`.
