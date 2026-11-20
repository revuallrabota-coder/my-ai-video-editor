/**
 * Без карты: Telegram Mini App -> Cloudflare Worker -> GitHub Actions.
 * Worker НЕ обрабатывает видео. FFmpeg и Whisper работают на GitHub runner.
 * Файл нужно отправить боту в Telegram после сообщения «Режим запущен».
 *
 * Настрой в Cloudflare Worker три секретных значения (НЕ в этом файле):
 * TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, GITHUB_PAT.
 *
 * GITHUB_PAT: fine-grained, только репозиторий
 * revuallrabota-coder/my-ai-video-editor, Actions: Read and write.
 */
const ORIGIN = "https://revuallrabota-coder.github.io";
const GITHUB_API =
  "https://api.github.com/repos/revuallrabota-coder/my-ai-video-editor/actions/workflows/test-without-api-id.yml/dispatches";

const CHOICES = {
  mode: ["my_style", "auto", "captions", "cuts", "reference"],
  subtitle_style: ["reference_dynamic", "signature", "contrast", "classic",
    "signature_phrases", "contrast_phrases", "classic_phrases"],
  camera_style: ["cinematic_pan", "editorial", "soft_punch", "enhanced", "gentle", "off"],
  video_filter: ["none", "warm"],
  caption_position: ["top", "middle", "bottom"],
  font_profile: ["elegant", "clean", "bold", "bebas", "platform", "bubble", "script", "modern"],
  audio_profile: ["off", "balanced", "strong"],
  video_speed: ["1.0", "1.1", "1.2"]
};

function json(value, status = 200, origin = ORIGIN) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
      "Vary": "Origin"
    }
  });
}

function field(value, name, defaultValue) {
  const v = String(value ?? defaultValue);
  if (!CHOICES[name].includes(v)) {
    throw new Error("Неверная настройка: " + name);
  }
  return v;
}

function workflowInputs(settings) {
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) {
    throw new Error("Настройки должны быть объектом.");
  }
  const color = String(settings.color ?? "auto");
  if (color !== "auto" && !/^#[a-fA-F0-9]{6}$/.test(color)) {
    throw new Error("Недопустимый цвет.");
  }
  const hook = String(settings.hook ?? "").trim();
  if (hook.length > 70) {
    throw new Error("Текст хука не должен превышать 70 символов.");
  }
  if (hook && settings.hook_position && settings.hook_position !== "start") {
    throw new Error(
      "Через этот запуск хук можно поставить в начале. " +
      "Для хука в конце напиши боту /hook end ТВОЙ ТЕКСТ перед отправкой видео."
    );
  }
  const speed = Number(settings.speed ?? 1);
  return {
    mode: field(settings.mode, "mode", "my_style"),
    subtitle_style: field(settings.subtitle_style, "subtitle_style", "reference_dynamic"),
    camera_style: field(settings.camera_style, "camera_style", "cinematic_pan"),
    color,
    video_speed: field(speed.toFixed(1), "video_speed", "1.0"),
    video_filter: field(settings.filter_style, "video_filter", "none"),
    caption_position: field(settings.caption_position, "caption_position", "middle"),
    font_profile: field(settings.font_profile, "font_profile", "elegant"),
    audio_profile: field(settings.audio_profile, "audio_profile", "balanced"),
    hook_text: hook
  };
}

function equalHex(a, b) {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return mismatch === 0;
}

async function signHmac(keyBytes, text, raw = false) {
  const key = await crypto.subtle.importKey(
    "raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signed = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(text))
  );
  return raw ? signed : Array.from(signed)
    .map(b => b.toString(16).padStart(2, "0")).join("");
}

async function validateTelegram(initData, token, owner) {
  if (!token || !owner) throw new Error("Секреты Cloudflare ещё не настроены.");
  if (typeof initData !== "string" || initData.length > 12000 || !initData) {
    throw new Error("Открой приложение через меню Telegram-бота.");
  }
  const data = new URLSearchParams(initData);
  const hash = data.get("hash") ?? "";
  data.delete("hash");
  if (!/^[a-fA-F0-9]{64}$/.test(hash)) throw new Error("Нет подписи Telegram.");
  const sorted = [...data.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([a, b]) => a + "=" + b).join("\n");
  const inner = await signHmac(new TextEncoder().encode("WebAppData"), token, true);
  const expected = await signHmac(inner, sorted);
  if (!equalHex(expected, hash.toLowerCase())) {
    throw new Error("Не прошла проверка Telegram-подписи.");
  }
  const issued = Number(data.get("auth_date"));
  if (!Number.isFinite(issued) || Math.abs(Date.now() / 1000 - issued) > 86400) {
    throw new Error("Открой мини-приложение заново из Telegram.");
  }
  let user;
  try { user = JSON.parse(data.get("user") ?? ""); }
  catch { throw new Error("Не найден Telegram-пользователь."); }
  if (String(user.id) !== String(owner)) {
    throw new Error("Запуск разрешён только владельцу бота.");
  }
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin");
    if (origin !== ORIGIN) return json({ error: "Неверный источник запроса." }, 403, "null");
    if (request.method === "OPTIONS") return json({}, 204);
    const path = new URL(request.url).pathname;
    if (request.method === "GET" && path === "/health") {
      return json({ status: "online", mode: "github-actions-launcher" });
    }
    if (request.method !== "POST" || path !== "/launch") {
      return json({ error: "Маршрут не найден." }, 404);
    }
    const length = Number(request.headers.get("Content-Length") ?? 0);
    if (length > 22000) return json({ error: "Слишком большой запрос." }, 413);
    let payload;
    try {
      const body = await request.text();
      if (body.length > 22000) throw new Error("Запрос слишком большой.");
      payload = JSON.parse(body);
    } catch {
      return json({ error: "Неверный формат настроек." }, 400);
    }
    try {
      await validateTelegram(
        payload.init_data, env.TELEGRAM_BOT_TOKEN, env.OWNER_TELEGRAM_ID
      );
      if (!env.GITHUB_PAT) throw new Error("Добавь секрет GITHUB_PAT в Cloudflare.");
      const inputs = workflowInputs(payload.settings);
      const response = await fetch(GITHUB_API, {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + env.GITHUB_PAT,
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2026-03-10",
          "User-Agent": "personal-telegram-video-editor"
        },
        body: JSON.stringify({ ref: "main", inputs })
      });
      if (!response.ok) {
        return json({
          error: "GitHub не запустил монтаж (HTTP " + response.status +
            "). Проверь GITHUB_PAT: Actions → Read and write и доступ к репозиторию."
        }, 502);
      }
      return json({
        started: true,
        message: "Монтаж запущен на GitHub Actions. Когда бот напишет " +
          "«Режим запущен», отправь ему исходное видео в Telegram (до 20 МБ).",
        runs_url: "https://github.com/revuallrabota-coder/my-ai-video-editor/actions/workflows/test-without-api-id.yml"
      }, 202);
    } catch (err) {
      return json({ error: String(err?.message || err) }, 403);
    }
  }
};
