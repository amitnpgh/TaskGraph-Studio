"""Reusable local knowledge, MCP connection catalog and Windows-protected secrets."""
import base64
import ctypes
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def protect(text, decrypt=False):
    if os.name != "nt":
        raise ValueError("Persistent credentials currently require Windows. Use an unauthenticated server here.")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    raw = base64.b64decode(text) if decrypt else text.encode()
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    api = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    api.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    api.restype = wintypes.BOOL
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError(f"Windows could not unlock/store this credential for the current user (error {ctypes.get_last_error()}).")
    try:
        result = ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))
    return result.decode() if decrypt else base64.b64encode(result).decode()


class Library:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "catalog.json"
        self.session_secrets = {}
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"knowledge": [], "connections": []}

    def save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def secret(self, cid, value=None, persist=True):
        if not cid.isalnum():
            raise ValueError("Invalid connection identifier")
        path = self.directory / (cid + ".secret")
        if value is not None:
            if persist:
                path.write_text(protect(value), encoding="ascii")
            elif path.exists():
                path.unlink()
            self.session_secrets[cid] = value
        if cid in self.session_secrets:
            return self.session_secrets[cid]
        return protect(path.read_text(encoding="ascii"), True) if path.exists() else ""

    def put(self, category, item):
        item = dict(item)
        item.setdefault("id", uuid.uuid4().hex)
        item["updated"] = datetime.now(timezone.utc).isoformat()
        rows = self.data[category]
        self.data[category] = [r for r in rows if r["id"] != item["id"]] + [item]
        self.save()
        return item

    def remove(self, category, cid):
        self.data[category] = [r for r in self.data[category] if r["id"] != cid]
        self.save()
        if category == "connections":
            self.clear_secret(cid)

    def clear_secret(self, cid):
        if not cid.isalnum(): raise ValueError("Invalid connection identifier")
        path = self.directory / (cid + ".secret")
        if path.exists(): path.unlink()
        self.session_secrets.pop(cid, None)

    def context(self, selected):
        entries = [r for r in self.data["knowledge"] if r["id"] in selected]
        text = "\n\n".join(f"LIBRARY ITEM: {r['name']}\nSource: {r.get('source') or 'User notes'}\nSaved: {r['updated']}\n{r['text']}" for r in entries)
        if len(text) > 120000:
            raise ValueError("Selected knowledge exceeds 120,000 characters. Select fewer items or shorten them.")
        return text
