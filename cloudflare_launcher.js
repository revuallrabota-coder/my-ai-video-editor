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

const GITHUB_UPLOAD_API =
  "https://api.github.com/repos/revuallrabota-coder/my-ai-video-editor/actions/workflows/upload-video-50mb.yml/dispatches";
const MAX_UPLOAD_BYTES = 50_000_000; // 50 MB, decimal
const UPLOAD_PART_BYTES = 4_000_000;
const UPLOAD_TTL = 3 * 60 * 60; // 3h automatic deletion if runner fails

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
      "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Init-Data",
      "Access-Control-Allow-Methods": "POST, GET, PUT, DELETE, OPTIONS",
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


function verifiedWorkerSettings(config) {
  const original = workflowInputs({
    ...config,
    hook: "",
    hook_position: "start"
  });
  if (original.mode === "reference") {
    throw new Error("Загрузка 50 МБ пока работает в режиме «Мой стиль», без отдельного референса.");
  }
  const hook = String(config.hook ?? "").trim().slice(0, 58);
  const position = String(config.hook_position ?? "off");
  if (!["off", "start", "end", "both"].includes(position)) {
    throw new Error("Неверное положение хука.");
  }
  const sound = String(config.sound_effects ?? "soft");
  if (!["off", "soft", "punch"].includes(sound)) {
    throw new Error("Неверный звуковой эффект.");
  }
  const emoji = String(config.emoji_mode ?? "on");
  if (!["off", "on"].includes(emoji)) {
    throw new Error("Неверный режим эмодзи.");
  }
  const quality = String(config.export_quality ?? "high");
  if (!["high", "balanced"].includes(quality)) {
    throw new Error("Недопустимое качество.");
  }
  const delay = Number(config.subtitle_delay ?? 0.30);
  if (!Number.isFinite(delay) || delay < -0.5 || delay > 1.5) {
    throw new Error("Синхронизация титров: от -0.5 до +1.5 сек.");
  }
  return {
    mode: original.mode,
    color: original.color,
    subtitle_style: original.subtitle_style,
    camera_style: original.camera_style,
    video_speed: original.video_speed,
    video_filter: original.video_filter,
    caption_position: original.caption_position,
    font_profile: original.font_profile,
    audio_profile: original.audio_profile,
    sound_effects: sound,
    emoji_mode: emoji,
    hook: position === "off" ? "" : hook,
    hook_position: position,
    export_quality: quality,
    subtitle_delay: delay
  };
}

function uploadKey(id, part) {
  return "user-video:" + id + ":" + part;
}

function idMatches(id) {
  return /^[a-f0-9-]{36}$/.test(id);
}

async function githubDispatch(endpoint, token, inputs) {
  if (!token) throw new Error("В Cloudflare не найден GITHUB_PAT.");
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + token,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "personal-telegram-video-editor"
    },
    body: JSON.stringify({ ref: "main", inputs })
  });
  if (!response.ok) {
    throw new Error("GitHub Actions не запущен (HTTP " + response.status + ").");
  }
}

async function workerUploadRoute(request, env, path) {
  if (!env.UPLOADS) {
    return json({error:"Для видео 50 МБ подключи KV namespace к Worker под именем UPLOADS."},503);
  }
  const internal = path.startsWith("/internal/upload/");
  if (internal) {
    const bearer = (request.headers.get("Authorization") ?? "").replace(/^Bearer /,"");
    if (!bearer || !env.TELEGRAM_BOT_TOKEN ||
        !equalHex(bearer, env.TELEGRAM_BOT_TOKEN)) {
      return json({error:"Unauthorized"},401);
    }
    const match = path.match(/^\/internal\/upload\/([a-f0-9-]{36})(?:\/(manifest|chunk\/\d+|result\/start|result\/finish|result\/\d+|release))?$/);
    if (!match || !idMatches(match[1])) return json({error:"Not found"},404);
    const id = match[1], operation=match[2] ?? "manifest";
    const meta = await env.UPLOADS.get(uploadKey(id,"meta"),"json");
    if (!meta || !["queued","done"].includes(meta.state)) {
      return json({error:"Upload metadata is not yet available"},409);
    }
    if (request.method === "GET" && operation === "manifest") {
      return json({
        id, size:meta.size, parts:meta.parts, original_name:meta.original_name,
        settings:meta.settings, chunk_size:UPLOAD_PART_BYTES
      });
    }
    const cm = operation.match(/^chunk\/(\d+)$/);
    if (request.method === "GET" && cm) {
      const index = Number(cm[1]);
      if (index < 0 || index >= meta.parts) return json({error:"Bad index"},400);
      const buffer = await env.UPLOADS.get(uploadKey(id,index),"arrayBuffer");
      if (!buffer) return json({error:"Chunk temporarily unavailable"},409);
      return new Response(buffer, {
        headers: {
          "Content-Type":"application/octet-stream",
          "Cache-Control":"no-store"
        }
      });
    }
    if (request.method === "POST" && operation === "result/start") {
      let input;
      try {input = await request.json();}
      catch {return json({error:"Bad result metadata"},400);}
      const size=Number(input.size);
      if (!Number.isSafeInteger(size) || size < 1024 || size > 250_000_000) {
        return json({error:"Result is too large for temporary KV"},413);
      }
      const count=Math.ceil(size/UPLOAD_PART_BYTES);
      if (meta.state !== "queued") return json({error:"Already finished"},409);
      await env.UPLOADS.put(uploadKey(id,"meta"),
        JSON.stringify({...meta,output:{size,parts:count,state:"uploading"}}),
        {expirationTtl:UPLOAD_TTL});
      return json({ok:true,parts:count});
    }
    const resultPart=operation.match(/^result\/(\d+)$/);
    if (request.method === "PUT" && resultPart) {
      const i=Number(resultPart[1]),o=meta.output;
      if (!o || o.state!=="uploading" || !Number.isSafeInteger(i)
          || i<0 || i>=o.parts) return json({error:"Bad result part"},409);
      const expected=Math.min(UPLOAD_PART_BYTES,o.size-i*UPLOAD_PART_BYTES);
      const buffer=await request.arrayBuffer();
      if(buffer.byteLength!==expected)return json({error:"Incorrect result chunk"},400);
      await env.UPLOADS.put(uploadKey(id,"output:"+i),buffer,{expirationTtl:UPLOAD_TTL});
      return json({ok:true,index:i});
    }
    if (request.method === "POST" && operation === "result/finish") {
      const o=meta.output;
      if (!o || o.state!=="uploading") return json({error:"No result upload"},409);
      for(let i=0;i<o.parts;i++){
        const buf=await env.UPLOADS.get(uploadKey(id,"output:"+i),"arrayBuffer");
        if (!buf || buf.byteLength!==Math.min(UPLOAD_PART_BYTES,o.size-i*UPLOAD_PART_BYTES)){
          return json({error:"Result KV chunk is not yet available"},409);
        }
      }
      await env.UPLOADS.put(uploadKey(id,"meta"),
        JSON.stringify({...meta,state:"done",output:{...o,state:"ready"}}),
        {expirationTtl:UPLOAD_TTL});
      return json({ok:true});
    }
    if (request.method === "DELETE" && operation === "release") {
      await Promise.all(
        Array.from({length:meta.parts},(_,i)=>env.UPLOADS.delete(uploadKey(id,i)))
      );
      // Keep the authenticated output available for an iPad download.
      if (!meta.output || meta.output.state!=="ready") {
        await env.UPLOADS.delete(uploadKey(id,"meta"));
      }
      return json({released:true});
    }
    return json({error:"Unknown internal route"},404);
  }

  // Every upload operation verifies signed Telegram initData.
  // The file is NEVER public: only the actual Telegram owner can upload.
  const initData = request.headers.get("X-Telegram-Init-Data");
  try {
    await validateTelegram(initData, env.TELEGRAM_BOT_TOKEN, env.OWNER_TELEGRAM_ID);
  } catch (err) {
    return json({error:String(err.message ?? err)},403);
  }
  // Only the verified Telegram owner may check/download final MP4 chunks.
  const clientStatus=path.match(/^\/upload\/([a-f0-9-]{36})\/status$/);
  if (request.method === "GET" && clientStatus) {
    const meta=await env.UPLOADS.get(uploadKey(clientStatus[1],"meta"),"json");
    if (!meta) return json({error:"Файл уже удалён или время хранения истекло."},404);
    const o=meta.output;
    return json({
      ready:meta.state==="done" && o?.state==="ready",
      size:o?.size ?? 0,parts:o?.parts ?? 0,
      state:meta.state
    });
  }
  const clientResult=path.match(/^\/upload\/([a-f0-9-]{36})\/result\/(\d+)$/);
  if (request.method === "GET" && clientResult) {
    const id=clientResult[1], i=Number(clientResult[2]);
    const meta=await env.UPLOADS.get(uploadKey(id,"meta"),"json");
    const o=meta?.output;
    if(!meta || meta.state!=="done" || o?.state!=="ready" || i<0 || i>=o.parts)
      return json({error:"Готовый ролик ещё не загружен."},409);
    const bytes=await env.UPLOADS.get(uploadKey(id,"output:"+i),"arrayBuffer");
    if(!bytes)return json({error:"Фрагмент результата пока недоступен."},409);
    return new Response(bytes,{
      headers:{
        "Content-Type":"application/octet-stream",
        "Cache-Control":"no-store",
        "Access-Control-Allow-Origin":ORIGIN,
        "Access-Control-Allow-Headers":"X-Telegram-Init-Data",
        "Vary":"Origin"
      }
    });
  }
  if (request.method === "POST" && path === "/upload/start") {
    let payload;
    try { payload = await request.json(); }
    catch { return json({error:"Неверный запрос на загрузку"},400); }
    const size=Number(payload.size);
    if (!Number.isSafeInteger(size) || size < 4096 || size > MAX_UPLOAD_BYTES) {
      return json({error:"Максимум 50 МБ для одного видео."},413);
    }
    const original=String(payload.filename ?? "");
    if (!/\.(mp4|mov|m4v|webm|mkv)$/i.test(original)) {
      return json({error:"Поддерживается видео MP4, MOV, M4V, WEBM или MKV."},400);
    }
    let settings;
    try {settings=verifiedWorkerSettings(payload.settings ?? {});}
    catch(err){return json({error:String(err.message ?? err)},400);}
    const id=crypto.randomUUID();
    const parts=Math.ceil(size/UPLOAD_PART_BYTES);
    await env.UPLOADS.put(
      uploadKey(id,"meta"),
      JSON.stringify({id,size,parts,original_name:original.slice(-120),
        settings,state:"uploading",created:Date.now()}),
      {expirationTtl:UPLOAD_TTL}
    );
    return json({upload_id:id,chunk_size:UPLOAD_PART_BYTES,parts},201);
  }

  const partPath=path.match(/^\/upload\/([a-f0-9-]{36})\/(\d+)$/);
  if (request.method === "PUT" && partPath) {
    const id=partPath[1],index=Number(partPath[2]);
    const meta=await env.UPLOADS.get(uploadKey(id,"meta"),"json");
    if (!meta || meta.state !== "uploading") {
      return json({error:"Загрузка не найдена или уже завершена."},409);
    }
    if (!Number.isSafeInteger(index) || index < 0 || index >= meta.parts) {
      return json({error:"Неверный номер части."},400);
    }
    const expected=Math.min(UPLOAD_PART_BYTES,meta.size-index*UPLOAD_PART_BYTES);
    const length=Number(request.headers.get("Content-Length") ?? 0);
    if (length && length !== expected) {
      return json({error:"Часть файла неверного размера."},400);
    }
    const buffer=await request.arrayBuffer();
    if (buffer.byteLength !== expected) {
      return json({error:"Часть файла не полностью загружена."},400);
    }
    await env.UPLOADS.put(uploadKey(id,index),buffer,{expirationTtl:UPLOAD_TTL});
    return json({uploaded:index+1,total:meta.parts});
  }

  const finish=path.match(/^\/upload\/([a-f0-9-]{36})\/finish$/);
  if (request.method === "POST" && finish) {
    const id=finish[1];
    const meta=await env.UPLOADS.get(uploadKey(id,"meta"),"json");
    if (!meta || meta.state !== "uploading") {
      return json({error:"Загрузка не найдена или уже запущена."},409);
    }
    // Confirm all parts have reached KV before launching GitHub.
    // KV is eventually consistent; retry in app when replicas lag.
    for (let i=0;i<meta.parts;i++) {
      const buffer=await env.UPLOADS.get(uploadKey(id,i),"arrayBuffer");
      const expected=Math.min(UPLOAD_PART_BYTES,meta.size-i*UPLOAD_PART_BYTES);
      if (!buffer || buffer.byteLength !== expected) {
        return json({error:"Часть "+(i+1)+" ещё не доступна в хранилище; повтори запуск."},409);
      }
    }
    try {
      await githubDispatch(GITHUB_UPLOAD_API,env.GITHUB_PAT,{
        upload_id:id,
        worker_url:new URL(request.url).origin
      });
    } catch(err) {
      return json({error:String(err.message ?? err)},502);
    }
    // Single KV write prevents the 1-write-per-second throttle on rollback.
    // GitHub runner retries reading metadata while KV replicates.
    await env.UPLOADS.put(
      uploadKey(id,"meta"),
      JSON.stringify({...meta,state:"queued"}),
      {expirationTtl:UPLOAD_TTL}
    );
    return json({
      started:true,
      message:"50 МБ переданы. GitHub скачает видео частями, смонтирует ролик и отправит MP4 в Telegram."
    },202);
  }
  return json({error:"Неизвестный маршрут загрузки"},404);
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    // Health can be checked in Safari; does not expose secrets.
    if (request.method === "GET" && path === "/health") {
      return json({ status: "online", mode: "github-actions-launcher",
        uploads_50mb_configured: Boolean(env.UPLOADS) });
    }
    if (path.startsWith("/internal/upload/")) {
      return workerUploadRoute(request, env, path);
    }
    const origin = request.headers.get("Origin");
    if (origin !== ORIGIN) return json({ error: "Неверный источник запроса." }, 403, "null");
    if (request.method === "OPTIONS") return json({}, 200);
    if (path.startsWith("/upload/")) {
      try { return await workerUploadRoute(request, env, path); }
      catch(err) {
        return json({error:"Ошибка загрузки: "+String(err.message ?? err)},500);
      }
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
          "X-GitHub-Api-Version": "2022-11-28",
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
