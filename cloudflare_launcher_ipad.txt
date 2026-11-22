// AI Reels Worker. Copy the entire file into Cloudflare > Edit code > Deploy.
// Required bindings: UPLOADS (KV), TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, GITHUB_PAT.
// Video processing happens in private GitHub Actions, never inside this Worker.
const ORIGIN = "https://revuallrabota-coder.github.io";
const REPOSITORY = "revuallrabota-coder/my-ai-video-editor";
const API = "https://api.github.com/repos/" + REPOSITORY + "/actions/workflows/";
const CHUNK = 4000000;
const MAX_VIDEO = 500000000;
const MAX_ASSETS = 100000000;
const TTL = 259200;
const CONTRACT = 4;
const STAGES = {
  queued:35, downloading:42, joining:53, transcribing:63, review:72,
  planning:78, rendering:86, publishing:94, done:100, failed:100
};
const CHOICES = {
  mode:"my_style auto captions cuts reference",
  subtitle_style:"reference_dynamic signature contrast classic signature_phrases contrast_phrases classic_phrases",
  camera_style:"cinematic_pan editorial soft_punch enhanced gentle off",
  video_filter:"none warm soft cool contrast clean film matte old_money vintage street elegant",
  caption_position:"top middle bottom",
  font_profile:"elegant clean bold bebas platform bubble script modern old_money vintage street refined roboto open_sans noto_sans ubuntu carlito lato_black modern_condensed",
  audio_profile:"off balanced strong",
  video_speed:"1.0 1.1 1.2 1.3 1.5",
  pause_removal:"off gentle balanced tight",
  caption_variant:"reference_soft editorial luxe minimal neon pop old_money vintage street elegant contour_talk cream_talk pistachio_talk burgundy_brown_talk",
  background_style:"off occasional frequent always",
  subject_layout:"standard behind beside",
  talk_scene:"off contour cream pistachio burgundy_brown",
  top_title_mode:"auto off intro always",
  animation_style:"float pop slide",
  subtitle_sfx:"off soft tick typewriter",
  insert_style:"off reference_soft retro old_money vintage elegant street editorial minimal neon pop luxe",
  insert_density:"subtle balanced dynamic",
  insert_sound:"off on",
  guide_effect:"off auto pov_carousel_spin liquid_glass_graph match_cut screen_push_digital apple_ui_toggles over_shoulder_zoom text_behind_me notification_stack phone_3d_float split_clones sticker_cutout zoom_through_text glass_explainer_reel cinematic_type_reel image_cluster_reel cutout_grid_reel depth_ui_reel split_reel"
};
CHOICES.small_font_profile = CHOICES.font_profile;

function response(data, status=200, origin=ORIGIN) {
  return new Response(JSON.stringify(data), {
    status, headers:{
      "Content-Type":"application/json; charset=utf-8",
      "Cache-Control":"no-store",
      "Access-Control-Allow-Origin":origin,
      "Access-Control-Allow-Headers":"Content-Type, X-Telegram-Init-Data",
      "Access-Control-Allow-Methods":"GET, POST, PUT, DELETE, OPTIONS",
      "Vary":"Origin"
    }
  });
}
function option(key, value, fallback) {
  const result = String(value ?? fallback);
  if (!CHOICES[key].split(" ").includes(result)) {
    throw new Error("Неверная настройка: " + key);
  }
  return result;
}
function parseSettings(s) {
  if (!s || typeof s!=="object" || Array.isArray(s)) {
    throw new Error("Неверный формат настроек.");
  }
  const color=String(s.color ?? "auto");
  if (color!=="auto" && !/^#[\da-fA-F]{6}$/.test(color)) {
    throw new Error("Неверный цвет субтитров.");
  }
  const title=String(s.top_title ?? "").trim();
  if (title.length>70 || /[\\{}\r\n]/.test(title)) {
    throw new Error("Название должно быть одной строкой до 70 символов.");
  }
  const hook=String(s.hook ?? "").trim().slice(0,58);
  const hookPosition=String(s.hook_position ?? "off");
  if (!["off","start","end","both"].includes(hookPosition)) {
    throw new Error("Неверное положение хука.");
  }
  const sound=String(s.sound_effects ?? "soft");
  const emoji=String(s.emoji_mode ?? "on");
  const quality=String(s.export_quality ?? "high");
  const delay=Number(s.subtitle_delay ?? 0);
  if (!["off","soft","punch","whoosh"].includes(sound) ||
      !["off","on"].includes(emoji) ||
      !["high","balanced"].includes(quality) ||
      !Number.isFinite(delay) || delay<-.5 || delay>1.5) {
    throw new Error("Неверная дополнительная настройка монтажа.");
  }
  const settings={
    mode:option("mode",s.mode,"my_style"),
    subtitle_style:option("subtitle_style",s.subtitle_style,"reference_dynamic"),
    color,
    camera_style:option("camera_style",s.camera_style,"cinematic_pan"),
    video_speed:option("video_speed",Number(s.speed ?? s.video_speed ?? 1.2).toFixed(1),"1.2"),
    video_filter:option("video_filter",s.filter_style ?? s.video_filter,"none"),
    caption_position:option("caption_position",s.caption_position,"middle"),
    font_profile:option("font_profile",s.font_profile,"elegant"),
    small_font_profile:option("small_font_profile",s.small_font_profile,"modern"),
    audio_profile:option("audio_profile",s.audio_profile,"balanced"),
    pause_removal:option("pause_removal",s.pause_removal,"tight"),
    caption_variant:option("caption_variant",s.caption_variant,"editorial"),
    background_style:option("background_style",s.background_style,"occasional"),
    subject_layout:option("subject_layout",s.subject_layout,"standard"),
    talk_scene:option("talk_scene",s.talk_scene,"off"),
    top_title:title,
    top_title_mode:option("top_title_mode",s.top_title_mode,"auto"),
    animation_style:option("animation_style",s.animation_style,"float"),
    subtitle_sfx:option("subtitle_sfx",s.subtitle_sfx,"soft"),
    sound_effects:sound,emoji_mode:emoji,
    hook:hookPosition==="off"?"":hook,
    hook_position:hookPosition,
    export_quality:quality,
    subtitle_delay:delay,
    insert_style:option("insert_style",s.insert_style,"reference_soft"),
    insert_density:option("insert_density",s.insert_density,"balanced"),
    insert_sound:option("insert_sound",s.insert_sound,"off"),
    guide_effect:option("guide_effect",s.guide_effect,"auto")
  };
  return settings;
}
function safeEqual(a,b) {
  a=String(a ?? ""); b=String(b ?? "");
  if (a.length!==b.length) return false;
  let diff=0;
  for (let i=0;i<a.length;i++) diff|=a.charCodeAt(i)^b.charCodeAt(i);
  return diff===0;
}
async function hmac(keyBytes,text,raw=false) {
  const key=await crypto.subtle.importKey("raw",keyBytes,
    {name:"HMAC",hash:"SHA-256"},false,["sign"]);
  const data=new Uint8Array(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode(text)));
  return raw ? data : Array.from(data,b=>b.toString(16).padStart(2,"0")).join("");
}
async function verifyTelegram(initData,env) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.OWNER_TELEGRAM_ID) {
    throw new Error("В Worker отсутствуют секреты Telegram.");
  }
  if (typeof initData!=="string" || !initData || initData.length>12000) {
    throw new Error("Открой мини-приложение из Telegram-бота.");
  }
  const params=new URLSearchParams(initData);
  const signature=params.get("hash") || "";
  params.delete("hash");
  if (!/^[\da-fA-F]{64}$/.test(signature)) {
    throw new Error("Отсутствует подпись Telegram.");
  }
  const check=[...params.entries()]
    .sort(([a],[b])=>a.localeCompare(b))
    .map(([a,b])=>a+"="+b).join("\n");
  const inner=await hmac(new TextEncoder().encode("WebAppData"),env.TELEGRAM_BOT_TOKEN,true);
  const actual=await hmac(inner,check);
  if (!safeEqual(signature.toLowerCase(),actual)) {
    throw new Error("Неверная Telegram-подпись.");
  }
  const issued=Number(params.get("auth_date"));
  if (!Number.isFinite(issued) || Math.abs(Date.now()/1000-issued)>86400) {
    throw new Error("Открой приложение заново из Telegram.");
  }
  let user;
  try {user=JSON.parse(params.get("user") || "");}
  catch {throw new Error("Нет данных Telegram-пользователя.");}
  if (String(user.id)!==String(env.OWNER_TELEGRAM_ID)) {
    throw new Error("Запуск разрешён только владельцу.");
  }
}
async function dispatch(workflow,pat,inputs) {
  if (!pat) throw new Error("В Cloudflare отсутствует GITHUB_PAT.");
  const r=await fetch(API+workflow+"/dispatches",{
    method:"POST",
    headers:{
      Authorization:"Bearer "+pat,
      Accept:"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"personal-telegram-video-editor"
    },
    body:JSON.stringify({ref:"main",inputs})
  });
  if (!r.ok) throw new Error("GitHub Actions: HTTP "+r.status);
}

const key=(id,item)=>"user-video:"+id+":"+item;
const validId=id=>/^[a-f0-9-]{36}$/.test(id);
const filesIn=meta=>[...(meta.files||[]),...(meta.assets||[])];
function expectedBytes(meta,i) {
  const f=filesIn(meta).find(f=>i>=f.offset && i<f.offset+f.parts);
  return f ? Math.min(CHUNK,f.size-(i-f.offset)*CHUNK) : -1;
}
async function completeParts(env,id,parts,prefix,meta=null) {
  const found=new Set();
  const base=key(id,prefix);
  let cursor;
  do {
    const page=await env.UPLOADS.list({prefix:base,limit:1000,...(cursor?{cursor}:{})});
    for (const item of page.keys) {
      const suffix=item.name.slice(base.length);
      if (!/^(0|[1-9]\d*)$/.test(suffix)) continue;
      const i=Number(suffix);
      const size=meta ? expectedBytes(meta,i) :
        Math.min(CHUNK,parts.total-i*CHUNK);
      if (Number.isSafeInteger(i) && i>=0 && i<parts.count &&
          item.metadata?.bytes===size) found.add(i);
    }
    cursor=page.list_complete ? null : page.cursor;
  } while (cursor);
  return found;
}
async function readJSON(request) {
  try {return await request.json();}
  catch {throw new Error("Неверный JSON в запросе.");}
}
async function uploadStart(request,env) {
  const body=await readJSON(request);
  const input=Array.isArray(body.files) ? body.files :
    [{name:body.filename,size:body.size}];
  const packages=body.assets ?? [];
  if (!Array.isArray(packages) || packages.length>4 ||
      input.length<1 || input.length>12) {
    throw new Error("Допустимо до 12 видео и до 4 ZIP-архивов.");
  }
  let offset=0;
  function describe(items,isAsset) {
    return items.map(item=>{
      const size=Number(item?.size),name=String(item?.name ?? "");
      const cap=isAsset?MAX_ASSETS:MAX_VIDEO;
      const min=isAsset?100:4096;
      const extension=isAsset?/\.zip$/i:/\.(mp4|mov|m4v|webm|mkv)$/i;
      if (!Number.isSafeInteger(size) || size<min || size>cap ||
          !extension.test(name)) throw new Error("Неверный файл или размер: "+name);
      const parts=Math.ceil(size/CHUNK);
      const result={name:name.slice(-120),size,parts,offset};
      offset+=parts;
      return result;
    });
  }
  const files=describe(input,false);
  const assets=describe(packages,true);
  const size=files.reduce((n,f)=>n+f.size,0);
  const assetSize=assets.reduce((n,f)=>n+f.size,0);
  if (size>MAX_VIDEO || assetSize>MAX_ASSETS ||
      size+assetSize>600000000 ||
      (body.size!==undefined && Number(body.size)!==size)) {
    throw new Error("Общий размер видео до 500 МБ, ZIP до 100 МБ.");
  }
  const settings=parseSettings(body.settings ?? {});
  if (settings.mode==="reference") {
    throw new Error("Для файлов до 500 МБ выбери «Мой стиль».");
  }
  const id=crypto.randomUUID();
  const now=Date.now();
  const meta={id,size,parts:offset,files,assets,asset_size:assetSize,
    original_name:files[0].name,settings,state:"uploading",
    created:now,expires_at:now+TTL*1000};
  await env.UPLOADS.put(key(id,"meta"),JSON.stringify(meta),{expirationTtl:TTL});
  return response({upload_id:id,chunk_size:CHUNK,parts:offset,
    accepted_talk_scene:settings.talk_scene,
    accepted_caption_variant:settings.caption_variant,
    style_contract_version:CONTRACT},201);
}
async function uploadChunk(request,env,id,index) {
  const meta=await env.UPLOADS.get(key(id,"meta"),"json");
  if (!meta || meta.state!=="uploading") return response({error:"Загрузка недоступна."},409);
  const i=Number(index);
  if (!Number.isSafeInteger(i) || i<0 || i>=meta.parts) return response({error:"Неверный номер части."},400);
  const expected=expectedBytes(meta,i);
  if (expected<1) return response({error:"Повреждён список частей."},400);
  const data=await request.arrayBuffer();
  if (data.byteLength!==expected) return response({error:"Неверный размер части."},400);
  await env.UPLOADS.put(key(id,i),data,{expirationTtl:TTL,metadata:{bytes:data.byteLength}});
  return response({uploaded:i+1,total:meta.parts});
}
async function finishUpload(request,env,id) {
  const meta=await env.UPLOADS.get(key(id,"meta"),"json");
  if (!meta || meta.state!=="uploading") return response({error:"Проект уже запущен или удалён."},409);
  const found=await completeParts(env,id,{count:meta.parts}, "",meta);
  if (found.size!==meta.parts) {
    return response({error:"Часть видео ещё не доступна в хранилище; повтори запуск."},409);
  }
  await dispatch("upload-video-50mb.yml",env.GITHUB_PAT,{
    upload_id:id,worker_url:new URL(request.url).origin
  });
  await env.UPLOADS.put(key(id,"meta"),
    JSON.stringify({...meta,state:"queued"}),{expirationTtl:TTL});
  await env.UPLOADS.put(key(id,"progress:queued"),"1",{
    expirationTtl:TTL,
    metadata:{stage:"queued",percent:35,message:"Задача передана монтажёру",at:Date.now()}
  });
  return response({started:true,message:"Видео передано в GitHub Actions. Подтверди текст через Telegram."},202);
}
async function status(env,id) {
  const meta=await env.UPLOADS.get(key(id,"meta"),"json");
  if (!meta) return response({error:"Загрузка удалена или срок хранения истёк."},404);
  const stages=await env.UPLOADS.list({prefix:key(id,"progress:"),limit:50});
  const latest=(stages.keys||[]).map(x=>x.metadata)
    .filter(x=>x && Object.hasOwn(STAGES,x.stage))
    .sort((a,b)=>(b.at??0)-(a.at??0))[0];
  const uploaded=meta.state==="uploading" ?
    await completeParts(env,id,{count:meta.parts},"",meta) : new Set();
  const out=meta.output;
  const phase=latest?.stage ??
    (meta.state==="uploading"?"uploading":meta.state==="done"?"done":"queued");
  return response({
    ready:meta.state==="done"&&out?.state==="ready",
    size:out?.size??0,parts:out?.parts??0,
    input_size:meta.size,input_parts:meta.parts,
    input_files:(meta.files||[]).map(f=>({name:f.name,size:f.size})),
    input_assets:(meta.assets||[]).map(f=>({name:f.name,size:f.size})),
    uploaded_parts:[...uploaded].sort((a,b)=>a-b),
    state:meta.state,stage:phase,
    accepted_talk_scene:meta.settings?.talk_scene??"off",
    accepted_caption_variant:meta.settings?.caption_variant??"reference_soft",
    style_contract_version:CONTRACT,
    stage_label:latest?.message ?? phase,
    progress_percent:latest?.percent ??
      (phase==="uploading"?Math.round(uploaded.size*32/Math.max(meta.parts,1)):phase==="done"?100:35),
    updated_at:latest?.at??meta.created,
    expires_at:out?.expires_at??meta.expires_at??meta.created+TTL*1000,
    retention_days:3
  });
}
async function downloadResult(env,id,index) {
  const meta=await env.UPLOADS.get(key(id,"meta"),"json");
  const o=meta?.output;
  const i=Number(index);
  if (meta?.state!=="done" || o?.state!=="ready" ||
      !Number.isSafeInteger(i) || i<0 || i>=o.parts) {
    return response({error:"Готовое видео ещё не доступно."},409);
  }
  const data=await env.UPLOADS.get(key(id,"output:"+i),"arrayBuffer");
  if (!data) return response({error:"Часть результата пока недоступна."},409);
  return new Response(data,{headers:{
    "Content-Type":"application/octet-stream","Cache-Control":"no-store",
    "Access-Control-Allow-Origin":ORIGIN,
    "Access-Control-Allow-Headers":"X-Telegram-Init-Data","Vary":"Origin"
  }});
}
async function internalRoute(request,env,path) {
  const token=(request.headers.get("Authorization")||"").replace(/^Bearer /,"");
  if (!token || !safeEqual(token,env.TELEGRAM_BOT_TOKEN)) {
    return response({error:"Unauthorized"},401);
  }
  const match=path.match(/^\/internal\/upload\/([a-f0-9-]{36})(?:\/(manifest|chunk\/\d+|result\/start|result\/finish|result\/\d+|release|progress))?$/);
  if (!match) return response({error:"Not found"},404);
  const id=match[1],operation=match[2]||"manifest";
  const meta=await env.UPLOADS.get(key(id,"meta"),"json");
  if (!meta || !["queued","done"].includes(meta.state)) {
    return response({error:"Upload metadata is not yet available"},409);
  }
  if (request.method==="GET" && operation==="manifest") {
    return response({id,size:meta.size,parts:meta.parts,
      original_name:meta.original_name,files:meta.files,assets:meta.assets||[],
      asset_size:meta.asset_size||0,settings:meta.settings,chunk_size:CHUNK});
  }
  const chunk=operation.match(/^chunk\/(\d+)$/);
  if (request.method==="GET" && chunk) {
    const i=Number(chunk[1]);
    if (i<0 || i>=meta.parts) return response({error:"Bad chunk"},400);
    const data=await env.UPLOADS.get(key(id,i),"arrayBuffer");
    return data ? new Response(data,{headers:{"Content-Type":"application/octet-stream","Cache-Control":"no-store"}})
      : response({error:"Chunk temporarily unavailable"},409);
  }
  if (request.method==="POST" && operation==="progress") {
    const body=await readJSON(request);
    const stage=String(body.stage??"");
    if (!Object.hasOwn(STAGES,stage)) return response({error:"Unknown stage"},400);
    const percent=STAGES[stage],at=Date.now();
    const message=String(body.message??stage).slice(0,180);
    await env.UPLOADS.put(key(id,"progress:"+stage),"1",{
      expirationTtl:TTL,metadata:{stage,percent,message,at}
    });
    return response({ok:true,stage,percent});
  }
  if (request.method==="POST" && operation==="result/start") {
    const info=await readJSON(request);
    const size=Number(info.size);
    if (meta.state!=="queued" || !Number.isSafeInteger(size) ||
        size<1024 || size>250000000) return response({error:"Bad result size"},413);
    const expires=Date.now()+TTL*1000;
    const count=Math.ceil(size/CHUNK);
    await env.UPLOADS.put(key(id,"meta"),JSON.stringify({
      ...meta,expires_at:expires,
      output:{size,parts:count,state:"uploading",expires_at:expires}
    }),{expirationTtl:TTL});
    return response({ok:true,parts:count});
  }
  const part=operation.match(/^result\/(\d+)$/);
  if (request.method==="PUT" && part) {
    const i=Number(part[1]),o=meta.output;
    if (!o || o.state!=="uploading" || i<0 || i>=o.parts) {
      return response({error:"Bad result part"},409);
    }
    const data=await request.arrayBuffer();
    if (data.byteLength!==Math.min(CHUNK,o.size-i*CHUNK)) {
      return response({error:"Bad result part size"},400);
    }
    await env.UPLOADS.put(key(id,"output:"+i),data,{
      expiration:Math.ceil(o.expires_at/1000),metadata:{bytes:data.byteLength}
    });
    return response({ok:true,index:i});
  }
  if (request.method==="POST" && operation==="result/finish") {
    const o=meta.output;
    if (!o || o.state!=="uploading") return response({error:"No result upload"},409);
    const found=await completeParts(env,id,{count:o.parts,total:o.size},"output:");
    if (found.size!==o.parts) return response({error:"Result parts not ready"},409);
    await env.UPLOADS.put(key(id,"meta"),JSON.stringify({
      ...meta,state:"done",output:{...o,state:"ready"}
    }),{expiration:Math.ceil(o.expires_at/1000)});
    return response({ok:true});
  }
  if (request.method==="DELETE" && operation==="release") {
    const from=Number(new URL(request.url).searchParams.get("from")??0);
    if (!Number.isSafeInteger(from) || from<0 || from>=meta.parts) {
      return response({error:"Bad cleanup cursor"},400);
    }
    const end=Math.min(meta.parts,from+30);
    await Promise.all(Array.from({length:end-from},(_,i)=>
      env.UPLOADS.delete(key(id,from+i))));
    return response({released:true,next:end,has_more:end<meta.parts});
  }
  return response({error:"Unknown internal route"},404);
}
async function publicRoute(request,env,path) {
  await verifyTelegram(request.headers.get("X-Telegram-Init-Data"),env);
  const statusMatch=path.match(/^\/upload\/([a-f0-9-]{36})\/status$/);
  if (request.method==="GET" && statusMatch) return status(env,statusMatch[1]);
  const resultMatch=path.match(/^\/upload\/([a-f0-9-]{36})\/result\/(\d+)$/);
  if (request.method==="GET" && resultMatch) {
    return downloadResult(env,resultMatch[1],resultMatch[2]);
  }
  if (request.method==="POST" && path==="/upload/start") {
    return uploadStart(request,env);
  }
  const part=path.match(/^\/upload\/([a-f0-9-]{36})\/(\d+)$/);
  if (request.method==="PUT" && part) {
    return uploadChunk(request,env,part[1],part[2]);
  }
  const finish=path.match(/^\/upload\/([a-f0-9-]{36})\/finish$/);
  if (request.method==="POST" && finish) {
    return finishUpload(request,env,finish[1]);
  }
  return response({error:"Неизвестный маршрут."},404);
}
async function legacyLaunch(request,env) {
  const body=await readJSON(request);
  await verifyTelegram(body.init_data,env);
  const s=parseSettings(body.settings||{});
  if (s.hook && s.hook_position!=="start") {
    return response({error:"В старом запуске хук возможен только в начале."},400);
  }
  await dispatch("test-without-api-id.yml",env.GITHUB_PAT,{
    mode:s.mode,subtitle_style:s.subtitle_style,camera_style:s.camera_style,
    color:s.color,video_speed:s.video_speed,video_filter:s.video_filter,
    caption_position:s.caption_position,font_profile:s.font_profile,
    audio_profile:s.audio_profile,hook_text:s.hook
  });
  return response({started:true,
    message:"Режим запущен. Пришли исходное видео в Telegram (до 20 МБ).",
    runs_url:"https://github.com/"+REPOSITORY+"/actions/workflows/test-without-api-id.yml"},202);
}
export default {
  async fetch(request,env) {
    const path=new URL(request.url).pathname;
    if (request.method==="GET" && (path==="/" || path==="/health")) {
      return response({
        status:"online",mode:"github-actions-launcher",
        max_upload_mb:500,max_files:12,retention_days:3,status_tracking:true,
        uploads_50mb_configured:Boolean(env.UPLOADS),
        uploads_300mb_configured:Boolean(env.UPLOADS),
        uploads_500mb_configured:Boolean(env.UPLOADS),
        style_contract_version:CONTRACT,
        supported_talk_scenes:CHOICES.talk_scene.split(" ")
      });
    }
    if (!env.UPLOADS && (path.startsWith("/upload/") ||
        path.startsWith("/internal/upload/"))) {
      return response({error:"Подключи KV namespace с именем UPLOADS."},503);
    }
    try {
      if (path.startsWith("/internal/upload/")) {
        return await internalRoute(request,env,path);
      }
      if (request.headers.get("Origin")!==ORIGIN) {
        return response({error:"Неверный источник запроса."},403,"null");
      }
      if (request.method==="OPTIONS") return response({});
      if (path.startsWith("/upload/")) return await publicRoute(request,env,path);
      if (request.method==="POST" && path==="/launch") {
        return await legacyLaunch(request,env);
      }
      return response({error:"Маршрут не найден."},404);
    } catch(error) {
      const message=String(error?.message??error);
      const status=/подпись|владельцу|Telegram|секреты/i.test(message)?403:
        /настройк|файл|размер|формат|цвет|JSON|название/i.test(message)?400:500;
      return response({error:message},status);
    }
  }
};
