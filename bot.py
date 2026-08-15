import ast
import asyncio
import json
import logging
import os
import re
import sys
import time
import zipfile
import subprocess
import importlib.util
from pathlib import Path

import psutil
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    InputFile
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Force pre-install common modules globally including user_agent
for pkg in ["requests", "user_agent", "fake-useragent", "beautifulsoup4", "opencv-python", "Pillow"]:
    try:
        __import__(pkg.split("-")[0])
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

# Bot Credentials
BOT_TOKEN = "8510238632:AAH2lV5dHWFjRR92-rihTkRaqipSg9v-i70"
ADMIN_ID = 8783170404

# Smart Package Name Mapper (Imports vs Pip Names)
MODULE_MAPPER = {
    "user_agent": "user_agent",
    "fake_useragent": "fake-useragent",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "telegram": "python-telegram-bot",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "crypto": "pycryptodome",
    "Crypto": "pycryptodome",
    "fitz": "PyMuPDF",
    "dns": "dnspython",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "serial": "pyserial",
    "dateutil": "python-dateutil",
    "jwt": "PyJWT",
    "websocket": "websocket-client",
    "socketio": "python-socketio",
    "requests": "requests",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "telethon": "telethon",
    "pyrogram": "pyrogram"
}

def auto_install_requirements(script_path):
    try:
        with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
            code_content = f.read()

        tree = ast.parse(code_content, filename=script_path)
        imports = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])

        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
            "os", "sys", "math", "json", "re", "ast", "subprocess", "time", "datetime",
            "random", "threading", "io", "socket", "urllib", "http", "collections",
            "itertools", "functools", "pathlib", "shutil", "logging", "asyncio", 
            "sqlite3", "hashlib", "base64", "typing", "struct", "string", "traceback"
        }

        for mod in imports:
            if mod not in stdlib:
                if importlib.util.find_spec(mod) is None:
                    package_name = MODULE_MAPPER.get(mod, mod)
                    try:
                        subprocess.check_call(
                            [sys.executable, "-m", "pip", "install", "--upgrade", package_name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                    except subprocess.CalledProcessError:
                        if package_name != mod:
                            subprocess.call(
                                [sys.executable, "-m", "pip", "install", "--upgrade", mod],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL
                            )
    except Exception as e:
        print(f"⚠️ Auto-install error: {e}")

BOT_START_TIME = time.time()
DATA_FILE = Path("bot_data.json")
WORKSPACES_DIR = Path("workspaces").resolve()
WORKSPACES_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("AdvancedLiveRunner")

ACTIVE_RUNNERS = {}
ANSI_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def remove_ansi_codes(text: str) -> str:
    return ANSI_REGEX.sub('', text)

def get_readable_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    res = []
    if d: res.append(f"{d}d")
    if h: res.append(f"{h}h")
    if m: res.append(f"{m}m")
    if s: res.append(f"{s}s")
    return " ".join(res) if res else "0s"

def load_data() -> dict:
    if not DATA_FILE.exists():
        return {"users": {}, "pending": [], "banned": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "pending": [], "banned": []}

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def is_approved(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    return str(user_id) in load_data().get("users", {})

def is_banned(user_id: int) -> bool:
    return user_id in load_data().get("banned", [])

class LiveRunner:
    def __init__(self, chat_id: int, script_path: Path, workspace: Path):
        self.chat_id = chat_id
        self.script_path = script_path
        self.workspace = workspace
        self.proc = None
        self.logs = ""
        self.live_msg = None
        self.status = "Initializing..."

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "requests", "user_agent", "fake-useragent", "beautifulsoup4", "opencv-python", "Pillow"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = os.path.pathsep.join(sys.path)
        env["TERM"] = "xterm-256color"

        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(self.script_path),
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
            env=env
        )
        self.status = "Running"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 Kill Process", callback_data=f"proc_kill_{self.chat_id}"),
             InlineKeyboardButton("🔄 Refresh Output", callback_data=f"proc_ref_{self.chat_id}")],
            [InlineKeyboardButton("📋 Download Logs", callback_data=f"proc_log_{self.chat_id}")]
        ])

        header = (
            f"🚀 **LIVE SCRIPT EXECUTION**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 **Script:** `{self.script_path.name}`\n"
            f"⚡ **PID:** `{self.proc.pid}` | 🟢 **Status:** `Running`\n"
            f"⌨️ *Terminal Input:* Direct message text bhej kar reply karein.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(header, parse_mode="Markdown")
        self.live_msg = await update.message.reply_text("🖥 **Terminal Console:**\n```\nStarting process...\n```", parse_mode="Markdown", reply_markup=kb)

        asyncio.create_task(self.stream_output(context))

    async def stream_output(self, context: ContextTypes.DEFAULT_TYPE):
        last_update = 0
        try:
            while True:
                chunk = await self.proc.stdout.read(1024)
                if not chunk:
                    break
                
                decoded_text = chunk.decode("utf-8", errors="replace")
                self.logs += remove_ansi_codes(decoded_text)

                now = asyncio.get_event_loop().time()
                if now - last_update > 1.2:
                    last_update = now
                    display_text = self.logs[-3500:].strip() or "Process active (waiting for I/O output)..."
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛑 Kill Process", callback_data=f"proc_kill_{self.chat_id}"),
                         InlineKeyboardButton("🔄 Refresh Output", callback_data=f"proc_ref_{self.chat_id}")],
                        [InlineKeyboardButton("📋 Download Logs", callback_data=f"proc_log_{self.chat_id}")]
                    ])
                    try:
                        await context.bot.edit_message_text(
                            chat_id=self.chat_id,
                            message_id=self.live_msg.message_id,
                            text=f"🖥 **Terminal Console:**\n```\n{display_text}\n```",
                            parse_mode="Markdown",
                            reply_markup=kb
                        )
                    except Exception:
                        pass

            await self.proc.wait()
            self.status = f"Finished (Exit Code: {self.proc.returncode})"
            final_text = self.logs[-3500:].strip() or "Process finished with no console output."
            try:
                await context.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.live_msg.message_id,
                    text=f"🏁 **Execution Finished** (Exit: `{self.proc.returncode}`):\n```\n{final_text}\n```",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Download Full Log", callback_data=f"proc_log_{self.chat_id}")]])
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Stream Error: {e}")
        finally:
            if self.chat_id in ACTIVE_RUNNERS:
                del ACTIVE_RUNNERS[self.chat_id]

    async def send_input(self, text: str):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.write((text + "\n").encode("utf-8"))
                await self.proc.stdin.drain()
            except Exception:
                pass

def get_main_keyboard(user_id: int):
    kb = [
        ["🛑 Stop Active Script", "⚡ Running Tasks"],
        ["📁 File Manager", "💻 Custom Shell Command"],
        ["🖥 System Stats"]
    ]
    if user_id == ADMIN_ID:
        kb.append(["👑 Admin Panel"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if is_banned(uid):
        await update.message.reply_text("⛔ **ACCESS DENIED:** You are banned from using this bot.", parse_mode="Markdown")
        return

    if is_approved(uid):
        text = (
            f"⚡ **ADVANCED PYTHON EXECUTION BOT** ⚡\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **User:** {user.mention_markdown()}\n"
            f"🔑 **Access Role:** `{'Administrator' if uid == ADMIN_ID else 'Authorized User'}`\n\n"
            f"📂 **Usage:** `.py` ya `.zip` file bhejo script ko live run karne ke liye."
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard(uid))
        return

    data = load_data()
    if uid in data.get("pending", []):
        await update.message.reply_text("⏳ Request is pending Admin approval.")
        return

    data.setdefault("pending", []).append(uid)
    save_data(data)

    await update.message.reply_text("⏳ **Access request sent to System Admin.**", parse_mode="Markdown")

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve User", callback_data=f"approve_{uid}"),
        InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_{uid}")
    ]])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 **New Authorization Request**\n👤 **Name:** {user.full_name}\n🆔 **User ID:** `{uid}`",
        parse_mode="Markdown",
        reply_markup=markup
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not is_approved(user_id) or is_banned(user_id):
        return

    if chat_id in ACTIVE_RUNNERS:
        runner = ACTIVE_RUNNERS[chat_id]
        if runner.proc and runner.proc.returncode is None:
            runner.proc.kill()
        del ACTIVE_RUNNERS[chat_id]

    doc = update.message.document
    clean_name = os.path.basename(doc.file_name).replace(" ", "_")
    
    workspace = (WORKSPACES_DIR / str(user_id)).resolve()
    workspace.mkdir(exist_ok=True)
    target_path = workspace / clean_name

    msg = await update.message.reply_text("📥 **Downloading file to workspace...**", parse_mode="Markdown")
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(target_path)

    if target_path.suffix.lower() == ".zip":
        await msg.edit_text("📦 **Unpacking ZIP archive...**", parse_mode="Markdown")
        with zipfile.ZipFile(target_path, 'r') as zf:
            zf.extractall(workspace)
        os.remove(target_path)
        py_files = list(workspace.glob("*.py"))
        if not py_files:
            await msg.edit_text("❌ **Error:** No Python (`.py`) file found in ZIP.", parse_mode="Markdown")
            return
        target_path = py_files[0]

    await msg.edit_text("🔍 **Checking and auto-installing requirements...**", parse_mode="Markdown")
    auto_install_requirements(target_path)

    await msg.delete()
    runner = LiveRunner(chat_id, target_path, workspace)
    ACTIVE_RUNNERS[chat_id] = runner
    await runner.start(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if not is_approved(user_id) or is_banned(user_id):
        return

    if context.user_data.get("awaiting_broadcast"):
        context.user_data["awaiting_broadcast"] = False
        data = load_data()
        users = list(data.get("users", {}).keys())
        sent = 0
        for u in users:
            try:
                await context.bot.send_message(chat_id=int(u), text=f"📢 **Admin Broadcast:**\n\n{text}", parse_mode="Markdown")
                sent += 1
            except Exception:
                pass
        await update.message.reply_text(f"✅ **Broadcast sent to {sent}/{len(users)} users.**", parse_mode="Markdown")
        return

    if text == "🛑 Stop Active Script":
        if chat_id in ACTIVE_RUNNERS:
            runner = ACTIVE_RUNNERS[chat_id]
            if runner.proc and runner.proc.returncode is None:
                runner.proc.kill()
                await update.message.reply_text(f"🛑 **Terminated:** `{runner.script_path.name}`", parse_mode="Markdown")
            del ACTIVE_RUNNERS[chat_id]
        else:
            await update.message.reply_text("ℹ️ No active running script in this chat.")
        return

    if text == "⚡ Running Tasks":
        if not ACTIVE_RUNNERS:
            await update.message.reply_text("ℹ️ No scripts are currently executing.")
            return

        keyboard = []
        msg = "⚡ **Active Processes:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for cid, runner in ACTIVE_RUNNERS.items():
            if runner.proc and runner.proc.returncode is None:
                msg += f"• 📄 `{runner.script_path.name}` | PID: `{runner.proc.pid}`\n"
                keyboard.append([InlineKeyboardButton(f"❌ Kill {runner.script_path.name}", callback_data=f"kill_{cid}")])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        return

    if text == "📁 File Manager":
        workspace = (WORKSPACES_DIR / str(user_id)).resolve()
        files = [f for f in workspace.iterdir() if f.is_file()]
        if not files:
            await update.message.reply_text("📁 **Workspace is empty.**", parse_mode="Markdown")
            return
        
        keyboard = []
        for f in files[:10]:
            size_kb = round(f.stat().st_size / 1024, 1)
            keyboard.append([
                InlineKeyboardButton(f"📄 {f.name} ({size_kb} KB)", callback_data="noop"),
                InlineKeyboardButton("⬇️", callback_data=f"dl_{f.name}"),
                InlineKeyboardButton("🗑", callback_data=f"del_{f.name}")
            ])
        await update.message.reply_text("📁 **Your Workspace Files:**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if text == "💻 Custom Shell Command":
        await update.message.reply_text("💻 Send any terminal/shell command (e.g., `pip list`, `python --version`).", parse_mode="Markdown")
        return

    if text == "🖥 System Stats":
        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        uptime = get_readable_time(int(time.time() - BOT_START_TIME))

        stats_msg = (
            f"🖥 **SERVER SYSTEM DASHBOARD**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ **CPU Load:** `{cpu}%`\n"
            f"🧠 **RAM Usage:** `{ram.percent}%` ({round(ram.used/(1024**3), 2)}GB / {round(ram.total/(1024**3), 2)}GB)\n"
            f"💾 **Disk Storage:** `{disk.percent}%`\n"
            f"⏱ **Bot Uptime:** `{uptime}`\n"
            f"🔥 **Active Tasks:** `{len(ACTIVE_RUNNERS)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(stats_msg, parse_mode="Markdown")
        return

    if text == "👑 Admin Panel" and user_id == ADMIN_ID:
        data = load_data()
        users_cnt = len(data.get('users', {}))
        pending_cnt = len(data.get('pending', []))
        banned_cnt = len(data.get('banned', []))
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_bc")],
            [InlineKeyboardButton("👥 Manage Pending Requests", callback_data="adm_pending")]
        ])
        await update.message.reply_text(
            f"👑 **SYSTEM ADMIN CONTROL PANEL**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 **Approved Users:** `{users_cnt}`\n"
            f"⏳ **Pending Requests:** `{pending_cnt}`\n"
            f"🚫 **Banned Users:** `{banned_cnt}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return

    if chat_id in ACTIVE_RUNNERS:
        await ACTIVE_RUNNERS[chat_id].send_input(text)
    else:
        workspace = (WORKSPACES_DIR / str(user_id)).resolve()
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONPATH"] = os.path.pathsep.join(sys.path)
            env["TERM"] = "xterm-256color"
            cmd_text = text.replace("python ", f'"{sys.executable}" ') if text.startswith("python ") else text
            proc = await asyncio.create_subprocess_shell(
                cmd_text,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await proc.communicate()
            res = (stdout.decode("utf-8", errors="replace") or stderr.decode("utf-8", errors="replace") or "Executed successfully with no output.")
            await update.message.reply_text(f"```\n{res[:3500]}\n```", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ **Execution Error:** {e}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    db = load_data()

    if data == "noop":
        return

    if data == "adm_pending":
        pending = db.get("pending", [])
        if not pending:
            await query.edit_message_text("⏳ **No pending requests.**", parse_mode="Markdown")
            return
        
        keyboard = []
        for p_uid in pending:
            keyboard.append([
                InlineKeyboardButton(f"👤 {p_uid}", callback_data="noop"),
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{p_uid}"),
                InlineKeyboardButton("🚫 Ban", callback_data=f"ban_{p_uid}")
            ])
        await query.edit_message_text("👥 **Pending User Requests:**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_bc":
        if user_id == ADMIN_ID:
            context.user_data["awaiting_broadcast"] = True
            await query.edit_message_text("📢 **Send the broadcast message text in chat now.**", parse_mode="Markdown")

    elif data.startswith("proc_kill_"):
        cid = int(data.split("_")[2])
        if cid in ACTIVE_RUNNERS:
            runner = ACTIVE_RUNNERS[cid]
            if runner.proc and runner.proc.returncode is None:
                runner.proc.kill()
            del ACTIVE_RUNNERS[cid]
            await query.edit_message_text("🛑 **Process killed.**", parse_mode="Markdown")

    elif data.startswith("proc_ref_"):
        cid = int(data.split("_")[2])
        if cid in ACTIVE_RUNNERS:
            runner = ACTIVE_RUNNERS[cid]
            display_text = runner.logs[-3500:].strip() or "No logs available yet..."
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛑 Kill Process", callback_data=f"proc_kill_{cid}"),
                 InlineKeyboardButton("🔄 Refresh Output", callback_data=f"proc_ref_{cid}")],
                [InlineKeyboardButton("📋 Download Logs", callback_data=f"proc_log_{cid}")]
            ])
            try:
                await query.edit_message_text(f"🖥 **Terminal Console (Refreshed):**\n```\n{display_text}\n```", parse_mode="Markdown", reply_markup=kb)
            except Exception:
                pass

    elif data.startswith("proc_log_"):
        cid = int(data.split("_")[2])
        runner = ACTIVE_RUNNERS.get(cid)
        logs = runner.logs if runner else "No active memory log found."
        log_file = Path(f"process_log_{cid}.txt")
        log_file.write_text(logs, encoding="utf-8")
        with open(log_file, "rb") as f:
            await context.bot.send_document(chat_id=user_id, document=InputFile(f, filename=f"log_{cid}.txt"))
        if log_file.exists():
            log_file.unlink()

    elif data.startswith("dl_"):
        fname = data.split("_", 1)[1]
        filepath = WORKSPACES_DIR / str(user_id) / fname
        if filepath.exists():
            with open(filepath, "rb") as f:
                await context.bot.send_document(chat_id=user_id, document=InputFile(f, filename=fname))

    elif data.startswith("del_"):
        fname = data.split("_", 1)[1]
        filepath = WORKSPACES_DIR / str(user_id) / fname
        if filepath.exists():
            filepath.unlink()
            await query.edit_message_text(f"🗑 **File Deleted:** `{fname}`", parse_mode="Markdown")

    elif data.startswith("approve_"):
        uid = int(data.split("_")[1])
        if uid in db.get("pending", []):
            db["pending"].remove(uid)
        db.setdefault("users", {})[str(uid)] = True
        save_data(db)
        await query.edit_message_text(f"✅ User `{uid}` Authorized!", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=uid, text="🎉 **Your Access Has Been Approved!** Send /start to open dashboard.")
        except Exception:
            pass

    elif data.startswith("ban_"):
        uid = int(data.split("_")[1])
        if uid in db.get("pending", []):
            db["pending"].remove(uid)
        if uid not in db.get("banned", []):
            db.setdefault("banned", []).append(uid)
        save_data(db)
        await query.edit_message_text(f"🚫 User `{uid}` Banned.", parse_mode="Markdown")

def main():
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN is missing!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🚀 Universal Runner Bot initialized & polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
