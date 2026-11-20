# Без банковской карты: запуск монтажа из Telegram Mini App

**Статус: код альтернативы уже в GitHub; Cloudflare Worker ещё НЕ создан в аккаунте пользователя, а новая цепочка не проверена end-to-end.**

Render запросил у пользователя банковскую карту и не принимает российскую. Это не ошибка бота; не нужно придумывать карту или обходить платёжную проверку.

**Схема:** Telegram Mini App (выбор настроек) → Cloudflare Workers Free (только проверка подписи Telegram и запуск) → GitHub Actions (настоящий FFmpeg, Whisper и код видеомонтажа) → видео возвращается личным Telegram-ботом.

Cloudflare Worker не хранит и не обрабатывает видео. Поэтому **сам файл надо отправить боту в чат после его сообщения о запуске**, максимум 20 МБ. Настройки выбираются в Mini App; включить/выключить дополнительные эмодзи/звуки и поставить хук в конце можно командами боту. Ограничение 20 МБ текущего Telegram Bot API остаётся. Прямая загрузка из Mini App и лимит 1 ГБ пока НЕ реализованы в этой схеме.

## Что уже подготовлено в GitHub

- \`cloudflare_launcher.js\` — защищённый Cloudflare Worker. Убедись, что используешь **свежую версию на main**.
- \`index.html\` — на последней странице теперь отдельная кнопка **«▶️ Запустить монтаж без карты»** и поле Cloudflare Worker URL.
- \`.github/workflows/test-without-api-id.yml\` — существующий тестовый монтаж, который принимает 10 параметров.
- У тебя уже настроены GitHub Actions Secrets \`TELEGRAM_BOT_TOKEN\` и \`OWNER_TELEGRAM_ID\`, если старый ручной запуск был успешным.

## Шаг 1. Создать бесплатный Cloudflare Worker на iPad

1. На iPad в Safari открой **https://dash.cloudflare.com/** и зарегистрируйся / войди.
2. Открой **Workers & Pages → Create**. Выбери **Worker** и создание с готовым Hello World (названия могут отличаться).
3. Дай имя, например \`my-video-launcher\`; выбери **Free**, если предлагается тариф. У Cloudflare существует бесплатный Workers-план без обязательной банковской карты, но если в твоём аккаунте всё-таки потребуется проверка, не пытайся её обходить.
4. Создай Worker, открой **Edit Code** / **Edit Worker**.
5. В Safari открой [cloudflare_launcher.js](https://github.com/revuallrabota-coder/my-ai-video-editor/blob/main/cloudflare_launcher.js) в нашем GitHub, скопируй ВСЁ содержимое и замени им пример Hello World в редакторе Cloudflare. Нажми **Deploy**.

В этом исходном JavaScript **нет секретных токенов**.

## Шаг 2. Создать ограниченный токен GitHub

В том же аккаунте GitHub:

1. Перейди **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Repository access: **Only select repositories** → \`my-ai-video-editor\`.
3. Repository permissions: **Actions → Read and write**. Остальные права не предоставляй, если GitHub прямо не требует технических read-only permissions.
4. Установи срок действия, например 90 дней, и нажми Generate.
5. Скопируй токен **один раз**, сохрани в безопасном менеджере паролей. Не вставляй его в GitHub-файлы, Mini App и сообщения. При истечении срока понадобится новый токен.

## Шаг 3. Добавить 3 секрета в Cloudflare

В Workers & Pages открой созданный Worker → **Settings → Variables and Secrets → Add → Type: Secret**:

| Secret Name | Secret Value |
|---|---|
| \`TELEGRAM_BOT_TOKEN\` | токен существующего бота из @BotFather |
| \`OWNER_TELEGRAM_ID\` | числовой Telegram ID владельца |
| \`GITHUB_PAT\` | fine-grained токен, созданный на шаге 2 |

Нажми **Deploy**/Save, чтобы секреты стали доступны Worker. Все значения должны быть скрыты как Secret. Render и его банковская карта больше не участвуют в запуске.

## Шаг 4. Подключить кнопку в Telegram Mini App

1. Скопируй настоящий URL Worker из Cloudflare, например \`https://my-video-launcher.ИМЯ.workers.dev\`. **Не копируй пример как реальный адрес.**
2. Проверь в Safari адрес \`https://ВАШ-WORKER.workers.dev/health\` — должен вернуться JSON со \`status: online\`. Это лишь проверка доступности Worker, не полный тест монтажа.
3. Открой свою Mini App **именно через меню Telegram-бота**, а не напрямую в Safari. Для защищённого запроса нужен \`Telegram.WebApp.initData\`.
4. Выбери стиль, шрифты, Zoom, звук; перейди к последнему экрану.
5. В блоке **«Без банковской карты: Cloudflare + GitHub Actions»** вставь URL Worker.
6. Нажми **«▶️ Запустить монтаж без карты»**. Кнопка запускает существующий GitHub Workflow автоматически, если Worker настроен.
7. Открой чат бота и дождись сообщения **«Режим запущен»**. Только после него вручную **пришли исходное видео до 20 МБ**. Подтверди слова через \`/ok\`, \`/fix\` или \`/text\`. Готовый MP4 придёт в Telegram, если обработка завершится успешно.
8. При ошибке посмотри [GitHub Actions](https://github.com/revuallrabota-coder/my-ai-video-editor/actions/workflows/test-without-api-id.yml). Для первого теста используй видео 10–20 секунд.

## Чем этот путь отличается от Render

- **Плюсы:** не нужна банковская карта; не нужно запускать FFmpeg на слабом бесплатном хостинге; тяжёлый видеомонтаж делает runner GitHub Actions. GitHub сообщает, что стандартные hosted runners для публичных репозиториев остаются бесплатными при соблюдении правил.
- **Минусы:** ролик пересылается отдельно в Telegram-чат; размер пока 20 МБ; процесс может быть медленным из-за подготовки runner; результат не скачивается напрямую из Mini App. Автоматическая загрузка до 1 ГБ всё ещё требует другой архитектуры.
- **Безопасность:** Worker проверяет подлинную Telegram HMAC-подпись и числовой ID владельца. GitHub PAT хранится только в Cloudflare Secret, не в публичном GitHub Pages.
- **Ограничение:** Worker не выдаёт 24/7 видеосервер, а только запускает сборку по запросу. Нельзя считать всю цепочку успешно проверенной до теста на реальном ролике.

Альтернатива для сегодняшнего теста без создания нового аккаунта: открыть [тестовый Workflow](https://github.com/revuallrabota-coder/my-ai-video-editor/actions/workflows/test-without-api-id.yml), нажать **Run workflow**, потом отправить видео боту. Работает независимо от Render/Cloudflare при корректных GitHub Secrets.
