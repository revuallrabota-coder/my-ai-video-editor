"""Offline checks: no Telegram credentials, real links or external network."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

bot=types.ModuleType("bot_api_editor")
bot.call_api=lambda *a,**kw: None
bot.send_text=lambda *a,**kw: None
editor=types.ModuleType("telegram_editor")
editor.duration_and_audio=lambda path:(20.0,True)
with patch.dict(sys.modules,{"bot_api_editor":bot,"telegram_editor":editor}):
    import yandex_source as ys

class Response:
    def __init__(self,data=None,content=b"",status=200,headers=None):
        self.data=data
        self.content=content
        self.status_code=status
        self.headers=headers or {}
        self.is_redirect=status in (301,302,303,307,308)
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def json(self):return self.data
    def iter_content(self,size):yield self.content

class Session:
    def __init__(self,responses):
        self.responses=iter(responses)
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append(url)
        return next(self.responses)

A="https://disk.yandex.ru/i/ExampleOne"
B="https://disk.360.yandex.ru/i/ExampleTwo"

class YandexTest(unittest.TestCase):
    def test_extract_order_and_duplicates(self):
        self.assertEqual(ys.public_links(A+"\n"+B+"\n"+A),[A,B])
        self.assertEqual(ys.public_links("https://example.org/a"),[])
    def test_hosts(self):
        for host in ["downloader.disk.yandex.ru","downloader.disk.yandex.com",
                     "downloader.dst.yandex.net","vla-storage.storage.yandex.net"]:
            self.assertTrue(ys.download_host("https://"+host+"/disk/file"))
        for url in ["https://storage.yandex.net.evil.example/file",
                    "https://localhost/file","http://downloader.disk.yandex.ru/file",
                    "https://downloader.disk.yandex.ru:1234/file",
                    "https://user@downloader.disk.yandex.ru/file"]:
            self.assertFalse(ys.download_host(url))
    def test_download_redirect(self):
        size=4096
        s=Session([Response({"type":"file","name":"clip.mov","size":size}),
                   Response({"href":"https://downloader.disk.yandex.ru/disk/abc"}),
                   Response(status=302,headers={"Location":"https://vla-storage.storage.yandex.net/file"}),
                   Response(content=b"x"*size)])
        with tempfile.TemporaryDirectory() as tmp:
            p=ys.fetch_public_video(A,Path(tmp),s,index=2)
            self.assertEqual(p.name,"clip_002.mov")
            self.assertEqual(p.stat().st_size,size)
    def test_disallowed_redirect(self):
        s=Session([Response({"type":"file","name":"clip.mov","size":4096}),
                   Response({"href":"https://downloader.disk.yandex.ru/disk/abc"}),
                   Response(status=302,headers={"Location":"https://example.com/file"})])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"неподдерживаемый домен"):
                ys.fetch_public_video(A,Path(tmp),s)
        self.assertEqual(len(s.calls),3)
    def test_aggregate_limit(self):
        s=Session([Response({"type":"file","name":"clip.mov","size":4096})])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"3 ГБ"):
                ys.fetch_public_video(A,Path(tmp),s,remaining=1024)
    def test_multiple_messages_explicit_start(self):
        def update(i,text):
            return {"update_id":i,"message":{"from":{"id":123},"chat":{"id":123,"type":"private"},
                      "message_id":i+10,"text":text}}
        replies=[{"message_id":1},[update(1,A+"\n"+B),update(2,A),update(3,"/montage")]]
        def fake_download(link,folder,**kw):
            target=folder/f'clip_{kw["index"]:03d}.mp4'
            target.write_bytes(b"x"*4096)
            return target
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules,{"telegram_editor":editor}), \
             patch.object(ys,"call_api",side_effect=replies),patch.object(ys,"send_text"), \
             patch.object(ys,"fetch_public_video",side_effect=fake_download) as dl:
            clips=ys.receive_yandex_source("fake",123,Path(tmp),lambda *a:None)
            self.assertEqual([p.name for p in clips],["clip_001.mp4","clip_002.mp4"])
            self.assertEqual(dl.call_count,2)

if __name__=="__main__":
    unittest.main()
