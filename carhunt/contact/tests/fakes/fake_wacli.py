#!/usr/bin/env python3
"""Fake wacli: chats from $FAKE_WACLI_ROOT/chats/<number>.json; `send` only appends to sends.txt.
Never talks to WhatsApp. FAKE_WACLI_SEND_DELAY (s) slows sends (lock tests); FAKE_WACLI_FAIL=1 fails them."""
import json
import os
import sys
import time

root = os.environ["FAKE_WACLI_ROOT"]
a = [x for x in sys.argv[1:] if x != "--json"]
if a[:2] == ["send", "text"]:
    if os.environ.get("WACLI_READONLY") != "0":
        print("read-only mode", file=sys.stderr)
        sys.exit(3)
    time.sleep(float(os.environ.get("FAKE_WACLI_SEND_DELAY") or 0))
    if os.environ.get("FAKE_WACLI_FAIL"):
        print("no LID found for +000", file=sys.stderr)
        sys.exit(1)
    with open(f"{root}/sends.txt", "a") as fh:
        fh.write(json.dumps({"argv": a, "t": time.time()}) + "\n")
    print(json.dumps({"success": True, "data": {"id": f"FAKE{int(time.time() * 1000)}"}}))
    sys.exit(0)
if a[:2] == ["messages", "list"]:
    msgs = []
    if "--chat" in a:
        p = f"{root}/chats/{a[a.index('--chat') + 1]}.json"
        msgs = json.load(open(p)) if os.path.exists(p) else []
    else:
        for f in sorted(os.listdir(f"{root}/chats")):
            msgs += json.load(open(f"{root}/chats/{f}"))
        if "--from-them" in a:
            msgs = [m for m in msgs if not m.get("FromMe")]
        if "--after" in a:
            after = a[a.index("--after") + 1]
            msgs = [m for m in msgs if m["Timestamp"] > after.replace("+00:00", "Z")]
    print(json.dumps({"success": True, "data": {"messages": msgs}}))
    sys.exit(0)
print("unsupported in fake: " + " ".join(a), file=sys.stderr)
sys.exit(2)
