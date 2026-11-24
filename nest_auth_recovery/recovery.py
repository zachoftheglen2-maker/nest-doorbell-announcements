"""Experimental session recovery. Never submits Google passwords or operates locks."""
import asyncio
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, quote
from aiohttp import ClientSession, ClientTimeout, web, WSMsgType
from playwright.async_api import async_playwright

DATA = Path("/data")
OPTS = json.loads((DATA / "options.json").read_text())
TOKEN = os.environ["SUPERVISOR_TOKEN"]
SUP = {"Authorization": "Bearer " + TOKEN}
NEST = "https://home.nest.com/"
PLUGIN = "homebridge-nest-accfactory"
ACCOUNT = OPTS["account_name"]
APP = OPTS["homebridge_app"]
INTERVAL = OPTS["check_interval"]
COOLDOWN = 1800
NOTICE = "nest_auth_recovery"
STATE = {"monitor": "starting", "browser": "starting", "recovery": "not attempted",
         "automatic_recovery": OPTS["automatic_recovery"]}
LOCK = asyncio.Lock()
CANDIDATE = None
CONTEXT = None
PAGE = None
SESSION = None
LAST_ATTEMPT = 0.0
LAST_NOTICE = None
LAST_FAILURE = None
PROCS = []
TASKS = set()

def log(message):
    print(message, flush=True)

def latest_auth(logs, account=ACCOUNT):
    for line in reversed(logs.splitlines()):
        if "[NestAccfactory]" not in line or ('"' + account + '"') not in line:
            continue
        if re.search(r"Successfully (authorised|performed token refresh) using Google account", line):
            return "authorised", line.strip()
        if re.search(r"(Authorisation failed|Token refresh failed) using Google account", line):
            return "failed", line.strip()
    return "unknown", ""

def validate_base():
    u = urlsplit(OPTS["homebridge_url"])
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("Invalid Homebridge URL")
    return OPTS["homebridge_url"].rstrip("/")

async def request(method, url, headers=None, data=None, text=False):
    async with SESSION.request(method, url, headers=headers, json=data,
                               allow_redirects=False, timeout=ClientTimeout(total=20)) as r:
        if not 200 <= r.status < 300:
            raise RuntimeError("HTTP " + str(r.status))
        if text:
            return await r.text()
        if r.status == 204:
            return None
        raw = await r.read()
        return json.loads(raw) if raw else None

async def notify(message):
    global LAST_NOTICE
    if message == LAST_NOTICE:
        return
    try:
        await request("POST", "http://supervisor/core/api/services/persistent_notification/create",
                      SUP, {"title": "Nest authentication recovery", "message": message, "notification_id": NOTICE})
        LAST_NOTICE = message
    except Exception:
        log("Could not send Home Assistant notification")

async def clear_notice():
    global LAST_NOTICE
    if LAST_NOTICE is None:
        return
    try:
        await request("POST", "http://supervisor/core/api/services/persistent_notification/dismiss",
                      SUP, {"notification_id": NOTICE})
        LAST_NOTICE = None
    except Exception:
        pass

async def observe(response):
    global CANDIDATE
    try:
        u = urlsplit(response.url)
        if (u.scheme != "https" or u.hostname != "accounts.google.com"
                or u.path != "/o/oauth2/iframerpc"
                or "action=issueToken" not in u.query or response.status != 200):
            return
        if "home.nest.com" not in response.url:
            return
        body = await response.json()
        if not isinstance(body, dict) or not body.get("access_token") or body.get("error"):
            return
        headers = await response.request.all_headers()
        cookie = headers.get("cookie", "")
        if not cookie or len(cookie) > 32768:
            return
        # Preserve updates to the existing cookie names returned by the successful exchange.
        pairs = {}
        for part in cookie.split(";"):
            if "=" in part:
                k,v = part.strip().split("=", 1)
                pairs[k] = v
        for h in await response.headers_array():
            if h["name"].lower() == "set-cookie":
                first = h["value"].split(";",1)[0]
                if "=" in first:
                    k,v = first.split("=",1)
                    if k in pairs and v and "max-age=0" not in h["value"].lower():
                        pairs[k] = v
        CANDIDATE = (time.monotonic(), response.url, "; ".join(k+"="+v for k,v in pairs.items()))
        STATE["browser"] = "valid Nest authentication response captured"
        log("Browser Nest authentication succeeded (credentials not logged)")
    except Exception:
        pass

def track_response(response):
    task = asyncio.create_task(observe(response))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)

async def browser_start():
    global CONTEXT, PAGE
    profile = DATA / "browser"
    profile.mkdir(mode=0o700, exist_ok=True)
    os.chown(profile, 10001, 10001)
    os.chmod(profile, 0o700)
    # The browser is a separate unprivileged process and does not inherit the Supervisor token.
    env = {"PATH":"/usr/bin:/bin", "DISPLAY":":99", "HOME":str(profile), "LANG":"C.UTF-8"}
    PROCS.append(subprocess.Popen(["Xvfb",":99","-screen","0","1280x800x24","-nolisten","tcp"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    await asyncio.sleep(1)
    PROCS.append(subprocess.Popen(["x11vnc","-display",":99","-localhost","-nopw","-forever","-shared","-rfbport","5900"],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    PROCS.append(subprocess.Popen(["runuser","-u","browser","--","env","-i", "PATH=/usr/bin:/bin","DISPLAY=:99","HOME="+str(profile),"LANG=C.UTF-8","chromium","--no-sandbox","--disable-dev-shm-usage","--no-first-run","--no-default-browser-check","--remote-debugging-address=127.0.0.1","--remote-debugging-port=9222","--user-data-dir="+str(profile/"profile"),"about:blank"], env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    pw = await async_playwright().start()
    for _ in range(30):
        try:
            browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222",timeout=3000)
            CONTEXT = browser.contexts[0]
            PAGE = CONTEXT.pages[0] if CONTEXT.pages else await CONTEXT.new_page()
            CONTEXT.on("response",track_response)
            STATE["browser"] = "ready; sign in using browser display"
            return
        except Exception:
            await asyncio.sleep(1)
    STATE["browser"] = "browser startup failed"

async def fresh_candidate():
    global CANDIDATE
    if PAGE is None or PAGE.is_closed():
        raise RuntimeError("Browser unavailable")
    CANDIDATE = None
    started = time.monotonic()
    STATE["browser"] = "waiting for Nest authentication"
    try:
        await PAGE.goto(NEST, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    for _ in range(60):
        if CANDIDATE and CANDIDATE[0] >= started:
            result = CANDIDATE
            CANDIDATE = None
            # Stop background Nest web requests from racing with the renewed relay session.
            try:
                await PAGE.goto("about:blank", timeout=5000)
            except Exception:
                pass
            return result[1:]
        await asyncio.sleep(1)
    STATE["browser"] = "no fresh valid response; interactive sign-in may be needed"
    return None

async def homebridge_recover(credentials):
    base = validate_base()
    if not OPTS["homebridge_username"] or not OPTS["homebridge_password"]:
        raise RuntimeError("Homebridge login not configured")
    login = await request("POST",base+"/api/auth/login",data={"username":OPTS["homebridge_username"],"password":OPTS["homebridge_password"]})
    auth = {"Authorization":"Bearer "+login["access_token"]}
    endpoint = base+"/api/config-editor/plugin/"+PLUGIN
    blocks = await request("GET",endpoint,auth)
    if not isinstance(blocks,list):
        raise RuntimeError("Unexpected plugin config format")
    matches = [(b,a) for b in blocks if isinstance(b,dict)
               for a in b.get("accounts",[]) if isinstance(a,dict) and a.get("type")=="google" and a.get("name")==ACCOUNT]
    if len(matches)!=1:
        raise RuntimeError("Expected exactly one named Google account")
    block, account = matches[0]
    bridge = block.get("_bridge",{}).get("username","")
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}",bridge):
        raise RuntimeError("Dedicated child bridge not configured")
    # Verify the child bridge exists before changing configuration.
    children = await request("GET",base+"/api/status/homebridge/child-bridges",auth)
    if not isinstance(children,list) or not any(isinstance(c,dict) and c.get("username")==bridge for c in children):
        raise RuntimeError("Child bridge not found in Homebridge API")
    account["issueToken"],account["cookie"] = credentials
    # Homebridge's config editor backs up configuration. Never overwrite unrelated blocks.
    await request("POST",endpoint,auth,blocks)
    await request("PUT",base+"/api/server/restart/"+quote(bridge,safe=""),auth)
    STATE["recovery"]="credentials updated; waiting for authorisation"
    log("Updated named Nest account and requested its child bridge restart")

async def recover():
    async with LOCK:
        STATE["recovery"]="attempting browser session recovery"
        result = await fresh_candidate()
        if not result:
            STATE["recovery"]="interactive sign-in needed or browser request unavailable"
            await notify("Nest authentication failed. Automatic recovery could not obtain a valid session. Open Nest Recovery and sign in if required. Existing Homebridge configuration was not changed.")
            return
        try:
            await homebridge_recover(result)
        except Exception as e:
            STATE["recovery"]="Homebridge recovery request failed; check its API and child bridge status"
            log("Recovery request failed: "+type(e).__name__)
            await notify("Nest recovery could not finish. Check Homebridge and its child bridge. The plugin configuration may have been saved before a restart failed.")

async def monitor():
    global LAST_ATTEMPT,LAST_FAILURE
    while True:
        try:
            if not re.fullmatch(r"[a-zA-Z0-9_-]+",APP):
                raise RuntimeError("Invalid Homebridge app slug")
            logs = await request("GET","http://supervisor/addons/"+APP+"/logs/latest",SUP,text=True)
            status,line = latest_auth(logs)
            if STATE["monitor"]!=status:
                log("Nest authentication monitor: "+status)
            STATE["monitor"]=status
            if status=="authorised":
                LAST_FAILURE=None
                await clear_notice()
                if STATE["recovery"]=="credentials updated; waiting for authorisation":
                    STATE["recovery"]="Homebridge reported successful authorisation"
            elif status=="failed":
                await notify("Homebridge reported a Google Nest authentication failure. Check Nest Recovery for status.")
                now=time.monotonic()
                if OPTS["automatic_recovery"] and not LOCK.locked() and line!=LAST_FAILURE and (LAST_ATTEMPT==0 or now-LAST_ATTEMPT>=COOLDOWN):
                    LAST_FAILURE=line
                    LAST_ATTEMPT=now
                    await recover()
        except Exception as e:
            STATE["monitor"]="log unavailable; check Homebridge app slug and Supervisor permission"
            log("Monitor error: "+type(e).__name__)
        await asyncio.sleep(INTERVAL)

@web.middleware
async def ingress_only(request,handler):
    if request.remote!="172.30.32.2":
        raise web.HTTPForbidden()
    return await handler(request)

async def index(request):
    return web.FileResponse("/app/index.html")

async def status(request):
    return web.json_response(STATE)

async def open_nest(request):
    if LOCK.locked() or PAGE is None or PAGE.is_closed():
        raise web.HTTPConflict()
    async with LOCK:
        try:
            await PAGE.goto(NEST,wait_until="domcontentloaded",timeout=20000)
        except Exception:
            STATE["browser"]="navigation did not complete; check browser display"
    return web.json_response({"ok":True})

async def test_browser(request):
    if LOCK.locked():
        raise web.HTTPConflict()
    async def test():
        async with LOCK:
            try:
                result=await fresh_candidate()
                STATE["browser_test"]="passed; no Homebridge changes" if result else "not passed; sign in and retry"
            except Exception:
                STATE["browser_test"]="browser unavailable"
    task=asyncio.create_task(test());TASKS.add(task);task.add_done_callback(TASKS.discard)
    return web.json_response({"ok":True})

async def vnc(request):
    ws=web.WebSocketResponse(protocols=("binary",),max_msg_size=2**20)
    await ws.prepare(request)
    try:
        reader,writer=await asyncio.open_connection("127.0.0.1",5900)
    except OSError:
        await ws.close();return ws
    async def outgoing():
        while chunk:=await reader.read(65536):
            await ws.send_bytes(chunk)
    async def incoming():
        async for message in ws:
            if message.type==WSMsgType.BINARY:
                writer.write(message.data);await writer.drain()
            elif message.type==WSMsgType.ERROR:
                break
    tasks=[asyncio.create_task(outgoing()),asyncio.create_task(incoming())]
    try:
        await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        writer.close();await ws.close()
    return ws

async def main():
    global SESSION
    async with ClientSession() as SESSION:
        app=web.Application(middlewares=[ingress_only])
        app.add_routes([web.get("/",index),web.get("/status",status),web.post("/open",open_nest),
                        web.post("/test",test_browser),web.get("/vnc",vnc)])
        app.router.add_static("/novnc/","/usr/share/novnc",show_index=False)
        runner=web.AppRunner(app,access_log=None)
        await runner.setup()
        await web.TCPSite(runner,"0.0.0.0",8099).start()
        browser_task=asyncio.create_task(browser_start())
        monitor_task=asyncio.create_task(monitor())
        try:
            await asyncio.Event().wait()
        finally:
            for t in [browser_task,monitor_task,*TASKS]:t.cancel()
            await runner.cleanup()
            for p in reversed(PROCS):
                if p.poll() is None:p.terminate()

if __name__=="__main__":
    asyncio.run(main())
