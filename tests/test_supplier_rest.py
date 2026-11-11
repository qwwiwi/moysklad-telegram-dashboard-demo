import hashlib
import http.client
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import supplier_keys
from intake_api import JournalHandler, ThreadingHTTPServer
from intake_store import connect


class SupplierRestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.temp.name)/"intake.sqlite3")
        self.env=patch.dict(os.environ,{"ALLOWED_TELEGRAM_IDS":"1,2","INTAKE_DB":self.db,"INTAKE_UPLOAD_DIR":self.temp.name+"/uploads"})
        self.env.start()
        with connect() as db:
            db.execute("INSERT INTO profiles VALUES(1,'supplier')")
            db.execute("INSERT INTO profiles VALUES(2,'employee')")
            db.commit()
        self.key=supplier_keys.create(self.db,1,"Accounting agent")
        self.other=supplier_keys.create(self.db,2,"Other agent")
        self.processing=patch.object(JournalHandler,"process_supplier_document")
        self.mock_process=self.processing.start()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),JournalHandler)
        self.server.db_path=self.db
        self.server.bot_token="not-used"
        self.server.owner_ids={1}
        self.server.public_origin="https://app.example.test"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close()
        self.processing.stop();self.env.stop();self.temp.cleanup()

    def request(self,method,path,body=None,key=None,headers=None):
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=3)
        fields={"Authorization":"Bearer "+(key or self.key["key"]),**(headers or {})}
        conn.request(method,path,body=body,headers=fields)
        response=conn.getresponse()
        result=response.status,json.loads(response.read())
        conn.close();return result

    def upload(self,body=b"sku,qty\nTEST,2\n",request_key="order-123",digest=None,key=None):
        return self.request("POST","/api/v1/documents",body,key,{
            "Content-Type":"application/octet-stream","X-File-Name":"invoice.csv",
            "Idempotency-Key":request_key,"X-Content-SHA256":digest or hashlib.sha256(body).hexdigest()})

    def test_membership_removal_denies_an_existing_key(self):
        with patch.dict(os.environ, {"ALLOWED_TELEGRAM_IDS":"2"}):
            self.assertEqual(self.request("GET","/api/v1/documents")[0],401)

    def test_digest_storage_revocation_and_user_isolation(self):
        self.assertNotIn(self.key["key"],Path(self.db).read_bytes().decode(errors="ignore"))
        self.assertFalse(supplier_keys.revoke(self.db,2,self.key["id"]))
        self.assertEqual(supplier_keys.list_keys(self.db,1)[0]["name"],"Accounting agent")
        self.assertTrue(supplier_keys.revoke(self.db,1,self.key["id"]))
        self.assertEqual(self.request("GET","/api/v1/documents")[0],401)

    def test_upload_retry_conflict_and_scoped_read(self):
        status,result=self.upload();self.assertEqual(status,201)
        record=result["id"]
        status,retry=self.upload();self.assertEqual(status,200);self.assertEqual(retry["id"],record)
        self.assertTrue(retry["reused"])
        self.assertEqual(self.upload(body=b"changed")[0],409)
        self.assertEqual(self.request("GET",f"/api/v1/documents/{record}",key=self.other["key"])[0],404)
        status,result=self.request("GET",f"/api/v1/documents/{record}")
        self.assertEqual(status,200);self.assertEqual(result["document"]["origin"],"API · Accounting agent")
        self.assertNotIn("storage_path",result["document"])
        self.assertEqual(self.request("GET","/api/v1/documents")[1]["scope"],"own")
        self.assertEqual(self.mock_process.call_count,1)
        with connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM journal").fetchone()[0],1)

    def test_checksum_failure_does_not_publish_or_block_retry(self):
        self.assertEqual(self.upload(digest="0"*64)[0],422)
        with connect() as db:self.assertEqual(db.execute("SELECT count(*) FROM journal").fetchone()[0],0)
        self.assertEqual(self.upload()[0],201)


if __name__=="__main__":unittest.main()
