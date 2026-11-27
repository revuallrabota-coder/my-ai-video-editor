# Бесплатный монтаж до 3 ГБ и 10 минут с iPad

**Не нужны R2, российская или иностранная карта.** Cloudflare SQLite-backed Durable Objects доступны на бесплатном Workers. Текущий бесплатный тариф хранит до 5 ГБ данных всех Durable Objects вместе; файл 3 ГБ занимает большую часть этого объёма. Для защиты от переполнения исходные части удаляются **после успешного скачивания GitHub**, перед передачей готового MP4. Хранилище автоматически очищается через 72 часа.

## Уже сделано в GitHub
- Код: [`cloudflare_launcher_do_v9.js`](./cloudflare_launcher_do_v9.js)
- Worker v9 использует прежний KV namespace `UPLOADS` **только для статуса** и `VIDEO_SHARDS` для видео.
- Исходник до 3 000 000 000 байт и до 10 минут; несколько роликов считаются вместе, максимум 12.
- Загрузка 4 МБ частями (750 частей на файл 3 ГБ), восстановление по статусу.
- Каждый Durable Object хранит до 100 частей (~400 МБ), всего 8 независимых объектов для видео на 3 ГБ.
- Автоочистка SQLite через alarms с лимитом 72 часа.
- Короткая Telegram-версия отправляется ботом, мастер доступен по временной **подписанной ссылке** через Safari и HTTP Range. Исходный звук сохраняется.
- `wrangler.do.v9.toml.template` содержит нужную регистрацию SQLite-backed класса `VideoChunkShard`, без публикации ID аккаунта.
- В GitHub Actions готово развёртывание: [🚀 Deploy бесплатный Worker v9](https://github.com/revuallrabota-coder/my-ai-video-editor/actions/workflows/deploy-free-do-v9.yml)

## Понадобятся 3 настройки в GitHub, один раз
Cloudflare не подключён к GitHub от имени помощника: **публикация Worker не происходит автоматически**. Для безопасной установки с iPad:

1. **Cloudflare Account ID.** Открой <https://dash.cloudflare.com/> → свой аккаунт → Workers & Pages → справа/в панели найди **Account ID**. Скопируй.
2. **Cloudflare API Token.** Cloudflare → My Profile → API Tokens → Create Token. Создай token с разрешениями на редактирование Workers Script и создание SQLite Durable Objects (доступ к нужному аккаунту). Скопируй токен в GitHub Secret, **не присылай его в чат**. Не используй Global API Key.
3. **UPLOADS KV Namespace ID.** Cloudflare → Storage & Databases → Workers KV → найди уже существующее хранилище, которое подключено к Worker под именем `UPLOADS`. Скопируй 32-символьный **Namespace ID**. Это **не** секрет Telegram и не сам текст `UPLOADS`.

На iPad открой GitHub: <https://github.com/revuallrabota-coder/my-ai-video-editor/settings/secrets/actions> → **New repository secret**. Создай 3 секрета с ТОЧНЫМИ именами:
- `CLOUDFLARE_ACCOUNT_ID` = Account ID из пункта 1
- `CLOUDFLARE_API_TOKEN` = API Token из пункта 2
- `CLOUDFLARE_UPLOADS_KV_ID` = Namespace ID из пункта 3

**Не сохраняй эти значения в обычных файлах репозитория и не отправляй их ассистенту.**

## Установка в один клик после настройки секретов

1. Открой [Deploy бесплатный Worker v9](https://github.com/revuallrabota-coder/my-ai-video-editor/actions/workflows/deploy-free-do-v9.yml).
2. Нажми **Run workflow → Run workflow**. GitHub скачает Wrangler, создаст SQLite Durable Object namespace миграцией `new_sqlite_classes`, привяжет `VIDEO_SHARDS`, сохранив прежние секреты Worker. Название прежнего Worker: `black-violet-9e64`.
3. Дождись зелёной галочки. При красной открой шаг с ошибкой; не заменяй код в Cloudflare вручную, потому что миграция SQLite namespace нужна отдельно.
4. Открой существующий адрес Worker: `https://black-violet-9e64.revuall-rabota.workers.dev/health`.
   Убедись в полях `"style_contract_version":9`, `"durable_storage_configured":true`, `"storage_mode":"do"`, `"max_upload_mb":3000`, `"max_video_seconds":600`.
5. Закрой Mini App Telegram и открой заново. Нажми **«Проверить подключённый Cloudflare»**. Он должен показать **Durable Objects подключены** и разрешить загрузку 751,7 МБ или большего исходника.

## Ограничения и честная проверка

- Без оплаты это максимум **5 ГБ во всех SQLite Durable Objects аккаунта суммарно**, а не безлимитный склад. Загружай **один тяжёлый проект за раз**.
- Новый Worker и тест имитации 3 ГБ в GitHub прошли проверку; **реальный экспорт десятиминутного трёхгигабайтного MP4 на GitHub runner пока не проверен**. GitHub имеет ограниченные диск, память и время выполнения; первый такой тест может потребовать дополнительной оптимизации.
- Текущая схема GitHub Actions вмещает не более **3 ГБ исходников** через бесплатный DO. Если ролик больше, нужен другой сервер/план, и обещать отсутствие лимита нельзя.
- **Скачивание MP4 через Safari** использует подписанный адрес на 2 часа. Ссылку открывай через отдельный браузер и сохраняй в приложение «Файлы».
- Если Cloudflare не позволит создать Durable Object даже при Free plan, проверь статус Workers Free и токена на конкретном аккаунте. Помощник не может обойти интерфейс подтверждения аккаунта.
- Источник: <https://developers.cloudflare.com/durable-objects/platform/limits/> и <https://developers.cloudflare.com/durable-objects/platform/pricing/>.

## При ошибке
- GitHub Actions → **Deploy бесплатный Worker v9**: проблемы с API Token/namespace/migration.
- GitHub Actions → **Бесплатная загрузка 3 ГБ через Durable Objects**: результат тестов кода.
- Мини-приложение → «Проверить подключённый Cloudflare»: фактически опубликованная версия.
