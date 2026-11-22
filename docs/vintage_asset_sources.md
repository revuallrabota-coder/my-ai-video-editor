# Vintage Cinema: каталог реальных материалов (22.11.2026)

Основа: пользовательский референс — тёмная плёнка с меткой PLAY, VHS-пыль/царапины, analog film burn, киноплёночная перфорация, обрывки газеты и матовая бумага. Кадры записи Pinterest НЕ являются лицензией на копирование чужих медиа.

## Видео: выбрать оригинал в максимально доступном разрешении

| Назначение | Страница источника | Монтаж |
|---|---|---|
| Пыль, царапины, плёночная грязь | https://pixabay.com/videos/film-dust-scratches-distressed-old-245078/ | Overlay Screen/Lighten 8–25%, без закрытия лица |
| Film burn, тёплая засветка | https://www.pexels.com/video/dynamic-light-leak-transitions-for-vintage-videos-30042779/ | 0.18–0.55 с между фрагментами |
| Плёнка с отверстиями | https://pixabay.com/videos/film-frame-texture-with-sprocket-hole-257438/ | На архивных полноэкранных перебивках |
| Сгоревшая плёнка с царапинами, 4K 50fps, 13s | https://www.pexels.com/video/overlay-of-burned-film-with-scratches-12987888/ | Короткая смысловая перебивка, не постоянно |
| Аналоговая плёночная вспышка | https://www.pexels.com/video/flashing-film-roll-12987892/ | Переход, не поверх субтитров |
| Старый фильм (подборка) | https://mixkit.co/free-stock-video/old-film/ | Выбирать только клипы Stock Video Free License |
| Кинозерно (подборка) | https://mixkit.co/free-stock-video/film-grain/ | Подложка на 5–15% при необходимости |

## Звуки: один звук на одну смысловую операцию

| Функция | Найти запись на странице | URL |
|---|---|---|
| Фоновый кинопроектор | Antique movie projector spinning (0:21) либо Vintage film projector working (0:24) | https://mixkit.co/free-sound-effects/movie-projector/ |
| Короткий старт/останов проектора | Explainer video foley projector film antique bell and howell start stop (0:29) | https://mixkit.co/free-sound-effects/movie-projector/ |
| Затвор | Vintage camera shutter (0:01) | https://mixkit.co/free-sound-effects/movie-projector/ |
| Перемотка | Reel to reel rewind (0:03) | https://mixkit.co/free-sound-effects/movie-projector/ |
| Перелистывание газеты | Page turn single (0:01) | https://mixkit.co/free-sound-effects/paper/ |
| Шелест / коллаж | Papers being moved or wrinkling (0:06) | https://mixkit.co/free-sound-effects/paper/ |
| Появление бумажной карточки | Paper slide (0:01) | https://mixkit.co/free-sound-effects/paper/ |

## Правила интеграции

- Хранить этот каталог как ССЫЛКИ; не включать сторонние исходные mp4/mp3 в публичный GitHub, ZIP шаблона, библиотеку ассетов для скачивания пользователями или коммерческую раздачу.
- До подключения конкретного исходника ещё раз проверить лицензию именно этого файла. Страница Mixkit может предлагать Free и Restricted video license. Не считать «доступно для просмотра» равнозначным «разрешено к использованию».
- Изображение говорящего человека остаётся полноценным кадром. Для мягкой текстуры применять низкую непрозрачность. Только короткие вставки могут скрывать человека целиком.
- Звук речи не изменять. Проектор не громче фона (-28…-22 dBFS как стартовая оценка с проверкой на слух); затвор/бумагу использовать единично и только на согласованной смысловой перебивке, без частых эффектов.
- Для коротких переходов использовать настоящие film burn/light leaks; для кадра допускается лёгкий flicker. Не усиливать мерцание до резких опасных вспышек.
- Текст «PLAY / Jan 01 1970» в пользовательском Pinterest-референсе НЕ переносить как настоящий таймкод: это может создавать ложное впечатление исходной записи. Если нужна маркировка, явно декоративная и без поддельных дат.
- Рекомендуемый pipeline: выбрать/легально получить источник → локально положить в приватный каталог Render-сервера → проверить размер, fps, duration, лицензию → FFmpeg overlay с условием по таймкоду; fallback: существующий программный vintage_cinema.py.

## Лицензии (проверено 22.11.2026)

- Mixkit sound effects: https://mixkit.co/license/modal/sfxFree/ — разрешено включать в конечные видеоработы, НЕЛЬЗЯ распространять сами ассеты в tool/template/with source files.
- Mixkit video free: https://mixkit.co/license/modal/videoFree/ — разрешены коммерческие видео, проверить ограничения и конкретную лицензию клипа.
- Pixabay: https://pixabay.com/service/license-summary/ — нельзя распространять Content standalone.
- Pexels: https://www.pexels.com/legal-pages/license/ — разрешено использование и изменение, нельзя перепродавать неизменённый контент или распространять на стоковых платформах.

**Статус:** каталог найден и сохранён; сторонние медиа не скачаны/не подключены к рендеру. Нужна отдельная проверка лицензионных файлов и реального MP4 перед утверждением.
