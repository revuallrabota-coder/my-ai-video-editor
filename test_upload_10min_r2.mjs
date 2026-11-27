// Worker v8 contract: R2 binary chunks + KV-only metadata for 10-minute projects.
// Fake multi-gigabyte sizes; never allocate actual gigabytes in GitHub CI.
import assert from "node:assert/strict";
import {createHmac,webcrypto} from "node:crypto";
import {readFile} from "node:fs/promises";
globalThis.crypto ??= webcrypto;
const src=await readFile(new URL("./cloudflare_launcher_r2_v8.js",import.meta.url),"utf8");
const {default:worker}=await import("data:text/javascript;base64,"+
  Buffer.from(src).toString("base64"));
const token="12345:TEST_R2_PRIVATE";
const idUser=232323;
const params=new URLSearchParams({
  auth_date:String(Math.floor(Date.now()/1000)),
  user:JSON.stringify({id:idUser})
});
const raw=[...params.entries()].sort(([a],[b])=>a.localeCompare(b))
  .map(([a,b])=>a+"="+b).join("\n");
const signingKey=createHmac("sha256","WebAppData").update(token).digest();
params.set("hash",createHmac("sha256",signingKey).update(raw).digest("hex"));
const base="https://10minute-test.workers.dev";
const origin="https://revuallrabota-coder.github.io";
const metadata=new Map(),binary=new Map();
let kvWrites=0,kvLists=0,r2Writes=0,dispatches=0;
const uploads={
  async put(key,value,options={}){
    metadata.set(key,{value,metadata:options.metadata??null});kvWrites++;
  },
  async get(key,type){
    const obj=metadata.get(key);
    if(!obj)return null;
    return type==="json"?JSON.parse(obj.value):obj.value;
  },
  async getWithMetadata(key){
    const obj=metadata.get(key);
    return obj ? {value:obj.value,metadata:obj.metadata}:{
      value:null,metadata:null};
  },
  async list(){kvLists++;throw Error("KV.list unavailable");},
  async delete(key){metadata.delete(key)}
};
const r2={
  async put(key,buffer){
    r2Writes++;
    binary.set(key,{size:buffer.byteLength,data:new Uint8Array(buffer)});
    return {key};
  },
  async get(key){
    const row=binary.get(key);
    if(!row)return null;
    return {size:row.size,
      body:new ReadableStream({start(controller){
        controller.enqueue(row.data||new Uint8Array([1,2,3]));
        controller.close();
      }})};
  },
  async list({prefix,limit=1000,cursor}){
    const keys=[...binary.keys()].filter(x=>x.startsWith(prefix)).sort();
    const start=Number(cursor||0);
    const page=keys.slice(start,start+limit);
    return {objects:page.map(key=>({key,size:binary.get(key).size})),
      truncated:start+limit<keys.length,
      cursor:start+limit<keys.length?String(start+limit):undefined};
  },
  async delete(key){binary.delete(key)}
};
const env={UPLOADS:uploads,VIDEO_FILES:r2,TELEGRAM_BOT_TOKEN:token,
  OWNER_TELEGRAM_ID:String(idUser),GITHUB_PAT:"faux"};
globalThis.fetch=async(url)=>{
  assert.match(String(url),/api.github.com\/repos\//);
  dispatches++;
  return new Response(null,{status:204});
};
async function request(path,method="GET",body,internal=false,environment=env){
  const headers=internal ? {Authorization:"Bearer "+token} :
    {Origin:origin,"X-Telegram-Init-Data":params.toString()};
  if(body&&!(body instanceof ArrayBuffer))headers["Content-Type"]="application/json";
  const req=new Request(base+path,{
    method,headers,body:body instanceof ArrayBuffer?body:
      body?JSON.stringify(body):undefined
  });
  const res=await worker.fetch(req,environment);
  let data;
  try{data=await res.json()}catch{data=null;}
  return {status:res.status,data};
}
const health=(await request("/health")).data;
assert.equal(health.max_video_seconds,600);
assert.equal(health.large_storage_configured,true);
assert.equal(health.max_upload_mb,4000);
assert.equal(health.style_contract_version,8);
const size=3_000_000_000;
const start=await request("/upload/start","POST",{
  files:[{name:"ten_minutes.mov",size:3_000_000_000}],
  size,settings:{mode:"my_style"}
});
assert.equal(start.status,201,JSON.stringify(start));
assert.equal(start.data.storage,"r2");
assert.equal(start.data.parts,750);
const uploadId=start.data.upload_id;
const bigMeta=JSON.parse(metadata.get("user-video:"+uploadId+":meta").value);
assert.equal(bigMeta.storage,"r2");
assert.equal(bigMeta.size,size);
assert.equal(bigMeta.parts,750);
assert.equal(kvWrites,1);
assert.equal((await request("/upload/"+uploadId+"/0","PUT",
  new ArrayBuffer(4_000_000))).status,200);
assert.equal(r2Writes,1);
assert.equal(binary.get(uploadId+"/source/0").size,4_000_000);
// Simulate the rest of the file without allocating gigabytes.
for(let i=1;i<750;i++)
  binary.set(uploadId+"/source/"+i,{size:4_000_000});
const status=await request("/upload/"+uploadId+"/status");
assert.equal(status.status,200);
assert.equal(status.data.uploaded_parts.length,750);
assert.equal(kvLists,0);
const finished=await request("/upload/"+uploadId+"/finish","POST",{done:true});
assert.equal(finished.status,202,JSON.stringify(finished));
assert.equal(dispatches,1);
const manifest=await request("/internal/upload/"+uploadId+"/manifest","GET",null,true);
assert.equal(manifest.data.storage,"r2");
const dataResponse=await request("/internal/upload/"+uploadId+"/chunk/0","GET",null,true);
assert.equal(dataResponse.status,200);
const outputSize=512_000_000;
assert.equal((await request("/internal/upload/"+uploadId+"/result/start",
  "POST",{size:outputSize},true)).status,200);
for(let i=0;i<128;i++)
  binary.set(uploadId+"/result/"+i,{size:4_000_000});
const resultReady=await request("/internal/upload/"+uploadId+"/result/finish",
 "POST",{},true);
assert.equal(resultReady.status,200,JSON.stringify(resultReady));
const ready=await request("/upload/"+uploadId+"/status");
assert.equal(ready.data.ready,true);
assert.equal(ready.data.storage,"r2");
assert.equal((await request("/upload/"+uploadId+"/result/0")).status,200);
const cleanup=await request("/internal/upload/"+uploadId+"/release?from=0",
  "DELETE",null,true);
assert.equal(cleanup.status,200);
assert.equal(cleanup.data.has_more,true);
assert.equal(binary.has(uploadId+"/source/0"),false);
assert.equal(binary.has(uploadId+"/result/0"),true);
// With no R2 binding existing 500MB projects must retain the KV path.
const legacy={...env,VIDEO_FILES:undefined};
const fallback=await request("/upload/start","POST",{
  files:[{name:"short.mp4",size:12_000_000}],size:12_000_000
},false,legacy);
assert.equal(fallback.status,201,JSON.stringify(fallback));
assert.equal(health.large_storage_configured,true);
const legacyHealth=(await request("/health","GET",undefined,false,legacy)).data;
assert.equal(legacyHealth.large_storage_configured,false);
assert.equal(legacyHealth.max_upload_mb,500);
const refused=await request("/upload/start","POST",{
  files:[{name:"too_big.mp4",size:800_000_000}],size:800_000_000
},false,legacy);
assert.equal(refused.status,400);
assert.equal(kvLists,0);
console.log("✓ 10-min R2 cloud accepts a single 3 GB video metadata, uploads binary via R2, downloads 512MB master, preserves old KV and rejects large without R2");
