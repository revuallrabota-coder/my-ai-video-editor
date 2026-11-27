/* Real local Wrangler/Miniflare integration, not a mock storage map.
   Uses Cloudflare's SQLite-backed Durable Object for one actual 4MB chunk. */
import assert from "node:assert/strict";
import {webcrypto,createHmac} from "node:crypto";
globalThis.crypto??=webcrypto;
const base="http://127.0.0.1:8787";
const origin="https://revuallrabota-coder.github.io";
const token="1234:LOCAL_SQLITE_TEST";
const owner=404040;
const query=new URLSearchParams({
  auth_date:String(Math.floor(Date.now()/1000)),
  user:JSON.stringify({id:owner})
});
const check=[...query.entries()].sort(([a],[b])=>a.localeCompare(b))
  .map(([a,b])=>a+"="+b).join("\n");
const key=createHmac("sha256","WebAppData").update(token).digest();
query.set("hash",createHmac("sha256",key).update(check).digest("hex"));
const auth={"Origin":origin,"X-Telegram-Init-Data":query.toString()};
async function request(path,method="GET",body,binary=false){
  const headers={...auth};
  if(body&&!binary)headers["Content-Type"]="application/json";
  const res=await fetch(base+path,{method,headers,
    body:binary?body:body?JSON.stringify(body):undefined});
  let json;try{json=await res.json()}catch{json=null}
  return {res,data:json};
}
const health=await request("/health");
assert.equal(health.res.status,200);
assert.equal(health.data.style_contract_version,9);
assert.equal(health.data.durable_storage_configured,true);
const upload=await request("/upload/start","POST",{
  files:[{name:"real-sqlite.mp4",size:8_000_000}],
  size:8_000_000,settings:{mode:"my_style"}
});
assert.equal(upload.res.status,201,JSON.stringify(upload.data));
assert.equal(upload.data.storage,"do");
const id=upload.data.upload_id;
const payload=new Uint8Array(4_000_000);
payload[0]=56;payload[payload.length-1]=45;
const part=await request("/upload/"+id+"/0","PUT",payload.buffer,true);
assert.equal(part.res.status,200,JSON.stringify(part.data));
const status=await request("/upload/"+id+"/status");
assert.equal(status.res.status,200,JSON.stringify(status.data));
assert.deepEqual(status.data.uploaded_parts,[0]);
assert.equal(status.data.input_parts,2);
assert.equal(status.data.storage,"do");
console.log("✓ REAL Cloudflare local SQLite Durable Objects accepted a 4MB video chunk and resumed status; no R2 and no card");
