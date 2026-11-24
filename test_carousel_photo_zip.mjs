import assert from "node:assert/strict";
import {File} from "node:buffer";
import fs from "node:fs";
import {createRequire} from "node:module";
globalThis.File=File;
const require=createRequire(import.meta.url);
const {makeCarouselPhotoZip}=require("./carousel_photo_zip.js");
assert.equal(await makeCarouselPhotoZip([]),null);
const images=[
  new File([new Uint8Array(500).fill(11)],"manicure-red.jpg",{lastModified:17}),
  new File([new Uint8Array(600).fill(99)],"studio-green.png",{lastModified:19}),
  new File([new Uint8Array(700).fill(172)],"nails-burgundy.webp",{lastModified:23}),
];
const archive=await makeCarouselPhotoZip(images);
assert.equal(archive.name,"user_carousel_photos.zip");
assert.equal(archive.lastModified,23);
assert.ok(archive.size>1900&&archive.size<2300);
fs.writeFileSync("/tmp/carousel_on_ipad.zip",
                 Buffer.from(await archive.arrayBuffer()));
await assert.rejects(()=>makeCarouselPhotoZip(images.slice(0,2)),/3–12/);
await assert.rejects(()=>makeCarouselPhotoZip([
  images[0],images[1],new File([new Uint8Array(500)],"unsafe.exe")
]),/JPG/);
console.log("✓ iPad photos become a private, ordered ZIP; invalid selections rejected.");
