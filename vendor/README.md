# Сторонние скрипты плеера

Локальные копии скриптов, которые страница плеера `player/hlsx.html` тянет с чужих
хостов. `msx.benzac.de` у части провайдеров заблокирован, и без `tvx-plugin.min.js`
плеер не стартует (вечный спиннер, `00:00:00`). Поэтому `api.py` отдаёт страницу
плеера со ссылками на эти файлы вместо оригинальных.

| Файл | Версия | Источник | sha256 |
|---|---|---|---|
| `tvx-plugin.min.js` | TVX Plugin v0.0.79 (фреймворк 0.1.35) | `https://msx.benzac.de/js/tvx-plugin.min.js`, снимок Wayback Machine от 2026-10-03 | `7cf9daabeb7787094433f7958fed41d2bedc561496e987d01fc070c6a0183684` |
| `hls.min.js` | hls.js 1.6.15 | `https://cdn.jsdelivr.net/npm/hls.js@1.6.15/dist/hls.min.js` | `413a83e2bb0c77ed0bf0be105d539d17ef45dfd984a0b13ecd3b14a901383938` |

`tvx-plugin.min.js` — (c) Benjamin Zachey. `hls.js` — Apache License 2.0,
https://github.com/video-dev/hls.js.

## Обновление

Если upstream поменяет версию hls.js в `player/hlsx.html`, обновите `hls.min.js` на ту же
версию, иначе плеер продолжит работать со старой.
