import asyncio
import sqlite3
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiohttp import web
from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ═══════════════════════════ БАЗА ДАННЫХ ═══════════════════════════
def init_db():
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, photo_url TEXT,
        balance REAL DEFAULT 10000, crystals INTEGER DEFAULT 10,
        income_per_hour REAL DEFAULT 0, level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0,
        energy INTEGER DEFAULT 100, max_energy INTEGER DEFAULT 100, last_collect TEXT,
        prestige INTEGER DEFAULT 0, crowns INTEGER DEFAULT 0,
        total_earned REAL DEFAULT 0, total_raids INTEGER DEFAULT 0,
        shield_until TEXT, vip_until TEXT, last_energy_refill TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS player_buildings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, building_type TEXT, level INTEGER DEFAULT 1
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS building_types (
        type TEXT PRIMARY KEY, name TEXT, emoji TEXT, base_cost REAL,
        base_income REAL, cost_multiplier REAL DEFAULT 2.0, income_multiplier REAL DEFAULT 1.5,
        unlock_level INTEGER DEFAULT 1
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS daily_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_type TEXT,
        target INTEGER, progress INTEGER DEFAULT 0, reward REAL, done INTEGER DEFAULT 0, date TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS achievements (
        id TEXT PRIMARY KEY, name TEXT, emoji TEXT, description TEXT,
        category TEXT, reward_crystals INTEGER DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS player_achievements (
        user_id INTEGER, ach_id TEXT, unlocked_at TEXT, PRIMARY KEY(user_id, ach_id)
    )""")
    
    cur.execute("SELECT COUNT(*) FROM building_types")
    if cur.fetchone()[0] == 0:
        for b in [
            ("stall","Ларёк","🏪",100,10,2.0,1.5,1),
            ("shop","Магазин","🏬",500,50,2.0,1.5,2),
            ("factory","Завод","🏭",2000,200,2.0,1.5,3),
            ("office","Офис","🏢",8000,500,2.0,1.5,5),
            ("supermarket","Супермаркет","🛒",20000,1000,2.0,1.5,7),
            ("warehouse","Склад","🏗️",50000,2000,2.0,1.5,10),
            ("restaurant","Ресторан","🍽️",100000,5000,2.0,1.5,15),
            ("mine","Шахта","⛏️",200000,10000,2.0,1.5,20),
            ("bank","Банк","🏦",500000,20000,2.0,1.5,30),
            ("tower","Небоскрёб","🏙️",1000000,50000,2.0,1.5,50)
        ]:
            cur.execute("INSERT INTO building_types VALUES (?,?,?,?,?,?,?,?)", b)
        conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM achievements")
    if cur.fetchone()[0] == 0:
        for a in [
            ("first_build","Первый кирпич","🧱","Постройте первое здание","build",5),
            ("five_builds","Застройщик","🏗️","Постройте 5 разных зданий","build",20),
            ("first_million","Миллионер","💵","Накопите 1 000 000 ₽","money",50),
            ("ten_million","Богач","💰","Накопите 10 000 000 ₽","money",100),
            ("first_raid","Налётчик","🥷","Совершите первый налёт","raid",10),
            ("fifty_raids","Крёстный отец","🔫","50 успешных налётов","raid",100),
            ("first_prestige","Новая жизнь","🔄","Сделайте престиж","prestige",200),
            ("all_common","Массовый бизнес","🏪","Постройте все здания","build",50),
        ]:
            cur.execute("INSERT INTO achievements VALUES (?,?,?,?,?,?)", a)
        conn.commit()
    conn.close()

def get_user(uid):
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (user_id) VALUES (?)", (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        row = cur.fetchone()
    conn.close()
    return {"user_id":row[0],"first_name":row[1],"username":row[2],"photo_url":row[3],"balance":row[4],"crystals":row[5],
            "income":row[6],"level":row[7],"xp":row[8],"energy":row[9],"max_energy":row[10],
            "last_collect":row[11],"prestige":row[12],"crowns":row[13],"total_earned":row[14],
            "total_raids":row[15],"shield_until":row[16],"vip_until":row[17],"last_energy_refill":row[18]}

def get_buildings(uid):
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("""SELECT pb.building_type, bt.name, bt.emoji, pb.level, bt.base_income, bt.income_multiplier
        FROM player_buildings pb JOIN building_types bt ON pb.building_type=bt.type WHERE pb.user_id=?""",(uid,))
    rows = cur.fetchall()
    conn.close()
    return [{"type":r[0],"name":r[1],"emoji":r[2],"level":r[3],"income":r[4]*(r[5]**(r[3]-1))} for r in rows]

def upd_income(uid):
    inc = sum(b["income"] for b in get_buildings(uid))
    user = get_user(uid)
    inc *= (1 + 0.1 * user["prestige"])
    if user["vip_until"] and user["vip_until"] > str(datetime.now()):
        inc *= 2
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET income_per_hour=? WHERE user_id=?",(round(inc,2),uid))
    conn.commit()
    conn.close()

def refill_energy(uid):
    u = get_user(uid)
    now = datetime.now()
    last = u["last_energy_refill"]
    if last:
        last = datetime.fromisoformat(last)
        minutes = (now - last).total_seconds() / 60
        recovered = int(minutes / 5) * 5
        if recovered > 0:
            new_energy = min(u["max_energy"], u["energy"] + recovered)
            conn = sqlite3.connect("game.db")
            cur = conn.cursor()
            cur.execute("UPDATE users SET energy=?, last_energy_refill=? WHERE user_id=?",(new_energy, now.isoformat(), uid))
            conn.commit()
            conn.close()

def check_achievements(uid):
    u = get_user(uid)
    blds = get_buildings(uid)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT ach_id FROM player_achievements WHERE user_id=?",(uid,))
    unlocked = {r[0] for r in cur.fetchall()}
    checks = {
        "first_build": len(blds) >= 1,
        "five_builds": len(blds) >= 5,
        "first_million": u["balance"] >= 1000000,
        "ten_million": u["balance"] >= 10000000,
        "first_raid": u["total_raids"] >= 1,
        "fifty_raids": u["total_raids"] >= 50,
        "first_prestige": u["prestige"] >= 1,
        "all_common": len({b["type"] for b in blds}) >= 4,
    }
    for ach_id, done in checks.items():
        if done and ach_id not in unlocked:
            cur.execute("INSERT OR IGNORE INTO player_achievements (user_id, ach_id) VALUES (?,?)",(uid, ach_id))
            cur.execute("SELECT reward_crystals FROM achievements WHERE id=?",(ach_id,))
            rw = cur.fetchone()
            if rw and rw[0]:
                cur.execute("UPDATE users SET crystals=crystals+? WHERE user_id=?",(rw[0], uid))
    conn.commit()
    conn.close()

def get_uid(request):
    uid = request.query.get("user_id", "0")
    return int(uid) if uid and uid.isdigit() else 0

# ═══════════════════════════ API ═══════════════════════════
async def api_data(request):
    uid = get_uid(request)
    refill_energy(uid)
    check_achievements(uid)
    u = get_user(uid)
    upd_income(uid)
    u = get_user(uid)
    blds = get_buildings(uid)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM building_types ORDER BY base_cost")
    all_b = [{"type":r[0],"name":r[1],"emoji":r[2],"base_cost":r[3],"base_income":r[4],"cost_mul":r[5],"inc_mul":r[6],"unlock_level":r[7]} for r in cur.fetchall()]
    cur.execute("""SELECT a.id, a.name, a.emoji, a.description, a.category, a.reward_crystals,
                   CASE WHEN pa.ach_id IS NOT NULL THEN 1 ELSE 0 END as unlocked
                   FROM achievements a 
                   LEFT JOIN player_achievements pa ON a.id=pa.ach_id AND pa.user_id=?""", (uid,))
    achs = [{"id":r[0],"name":r[1],"emoji":r[2],"desc":r[3],"category":r[4],"reward":r[5],"unlocked": bool(r[6])} for r in cur.fetchall()]
    conn.close()
    return web.json_response({"user":u,"buildings":blds,"all_buildings":all_b,"achievements":achs})

async def api_build(request):
    uid = get_uid(request)
    tp = request.query.get("type","")
    u = get_user(uid)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM building_types WHERE type=?",(tp,))
    bt = cur.fetchone()
    if u["level"] < bt[7]:
        conn.close()
        return web.json_response({"success":False,"error":f"Нужен {bt[7]} уровень!"})
    cur.execute("SELECT level FROM player_buildings WHERE user_id=? AND building_type=?",(uid,tp))
    ex = cur.fetchone()
    lvl = ex[0] if ex else 0
    cost = bt[3]*(bt[5]**lvl)
    if u["balance"]<cost:
        conn.close()
        return web.json_response({"success":False,"error":f"Не хватает {cost-u['balance']:,.0f} ₽"})
    cur.execute("UPDATE users SET balance=balance-?, xp=xp+5 WHERE user_id=?",(cost,uid))
    if ex:
        cur.execute("UPDATE player_buildings SET level=level+1 WHERE user_id=? AND building_type=?",(uid,tp))
    else:
        cur.execute("INSERT INTO player_buildings (user_id,building_type,level) VALUES (?,?,1)",(uid,tp))
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("UPDATE daily_tasks SET progress=progress+1 WHERE user_id=? AND task_type='build' AND date=? AND done=0",(uid,today))
    cur.execute("UPDATE users SET level=CASE WHEN xp>=level*50 THEN level+1 ELSE level END WHERE user_id=?",(uid,))
    conn.commit()
    conn.close()
    upd_income(uid)
    check_achievements(uid)
    return web.json_response({"success":True,"user":get_user(uid),"buildings":get_buildings(uid)})

async def api_collect(request):
    uid = get_uid(request)
    u = get_user(uid)
    now = datetime.now()
    earned = 0
    if u["last_collect"]:
        h = (now - datetime.fromisoformat(u["last_collect"])).total_seconds()/3600
        earned = min(u["income"]*h, u["income"]*24)
    if earned>0:
        conn = sqlite3.connect("game.db")
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+?, xp=xp+10, last_collect=? WHERE user_id=?",(round(earned,2),round(earned,2),now.isoformat(),uid))
        today = now.strftime("%Y-%m-%d")
        cur.execute("UPDATE daily_tasks SET progress=progress+1 WHERE user_id=? AND task_type='collect' AND date=? AND done=0",(uid,today))
        conn.commit()
        conn.close()
    return web.json_response({"earned":round(earned,2),"user":get_user(uid)})

async def api_top(request):
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT first_name, username, photo_url, balance, level, prestige FROM users ORDER BY balance DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    return web.json_response([{"name":r[0] or r[1] or "Игрок","photo":r[2],"balance":r[3],"level":r[4],"prestige":r[5]} for r in rows])

async def api_raid(request):
    uid = get_uid(request)
    u = get_user(uid)
    if u["energy"]<20:
        return web.json_response({"success":False,"error":"Недостаточно энергии!"})
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id,first_name,balance FROM users WHERE user_id!=? AND balance>100 ORDER BY RANDOM() LIMIT 1",(uid,))
    t = cur.fetchone()
    if not t:
        conn.close()
        return web.json_response({"success":False,"error":"Нет целей"})
    ok = random.random()<0.45
    cur.execute("UPDATE users SET energy=energy-20 WHERE user_id=?",(uid,))
    if ok:
        stolen = min(t[2]*0.1,100000)
        cur.execute("UPDATE users SET balance=balance+?, xp=xp+15, total_raids=total_raids+1 WHERE user_id=?",(stolen,uid))
        cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(stolen,t[0]))
        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute("UPDATE daily_tasks SET progress=progress+1 WHERE user_id=? AND task_type='raid' AND date=? AND done=0",(uid,today))
        conn.commit()
        conn.close()
        check_achievements(uid)
        return web.json_response({"success":True,"stolen":stolen,"user":get_user(uid)})
    else:
        fine = random.randint(500,5000)
        cur.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(fine,uid))
        conn.commit()
        conn.close()
        return web.json_response({"success":False,"error":f"Провал! -{fine} ₽","user":get_user(uid)})

async def api_tasks(request):
    uid = get_uid(request)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*) FROM daily_tasks WHERE user_id=? AND date=?",(uid,today))
    if cur.fetchone()[0] == 0:
        for tt, tg, rw in [("build",3,5000),("collect",5,3000),("raid",3,8000)]:
            cur.execute("INSERT INTO daily_tasks (user_id,task_type,target,reward,date) VALUES (?,?,?,?,?)",(uid,tt,tg,rw,today))
        conn.commit()
    cur.execute("SELECT id,task_type,target,progress,reward,done FROM daily_tasks WHERE user_id=? AND date=?",(uid,today))
    tasks = [{"id":r[0],"type":r[1],"target":r[2],"progress":r[3],"reward":r[4],"done":r[5]} for r in cur.fetchall()]
    conn.close()
    return web.json_response(tasks)

async def api_claim_task(request):
    uid = get_uid(request)
    tid = request.query.get("task_id","0")
    tid = int(tid) if tid.isdigit() else 0
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM daily_tasks WHERE id=? AND user_id=? AND done=0",(tid,uid))
    task = cur.fetchone()
    if task and int(task[4]) >= int(task[3]):
        cur.execute("UPDATE daily_tasks SET done=1 WHERE id=?",(tid,))
        cur.execute("UPDATE users SET balance=balance+?, crystals=crystals+1, xp=xp+50 WHERE user_id=?",(task[5],uid))
        conn.commit()
        conn.close()
        resp = web.json_response({"success":True,"reward":task[5],"user":get_user(uid)})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    conn.close()
    resp = web.json_response({"success":False})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

async def api_prestige(request):
    uid = get_uid(request)
    u = get_user(uid)
    if u["balance"] < 10000000:
        return web.json_response({"success":False})
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=1000, prestige=prestige+1, crowns=crowns+1 WHERE user_id=?",(uid,))
    cur.execute("DELETE FROM player_buildings WHERE user_id=?",(uid,))
    conn.commit()
    conn.close()
    upd_income(uid)
    check_achievements(uid)
    return web.json_response({"success":True,"user":get_user(uid),"buildings":get_buildings(uid)})

async def api_buy_energy(request):
    uid = get_uid(request)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET energy=max_energy, crystals=crystals-10 WHERE user_id=? AND crystals>=10", (uid,))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "user": get_user(uid)})

async def api_buy_money(request):
    uid = get_uid(request)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=balance+50000, crystals=crystals-25 WHERE user_id=? AND crystals>=25", (uid,))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "user": get_user(uid)})

async def api_buy_shield(request):
    uid = get_uid(request)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET crystals=crystals-50, shield_until=? WHERE user_id=? AND crystals>=50", 
                ((datetime.now() + timedelta(hours=24)).isoformat(), uid))
    conn.commit()
    conn.close()
    return web.json_response({"success": True, "user": get_user(uid)})

async def api_buy_vip(request):
    uid = get_uid(request)
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET crystals=crystals-200, vip_until=? WHERE user_id=? AND crystals>=200",
                ((datetime.now() + timedelta(days=7)).isoformat(), uid))
    conn.commit()
    conn.close()
    upd_income(uid)
    return web.json_response({"success": True, "user": get_user(uid)})

# ═══════════════════════════ БОТ ═══════════════════════════
@dp.message(Command("start"))
async def start(msg: types.Message):
    init_db()
    photos = await msg.from_user.get_profile_photos()
    photo_url = photos.photos[0][0].file_id if photos.total_count > 0 else None
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users (user_id, first_name, username, photo_url) VALUES (?,?,?,?)",
                (msg.from_user.id, msg.from_user.first_name, msg.from_user.username, photo_url))
    conn.commit()
    conn.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 ИГРАТЬ", web_app=WebAppInfo(url="https://89000900411pasha1-ship-it.github.io/biz-empire/"))]
    ])
    await msg.answer("👑 <b>БИЗНЕС-ИМПЕРИЯ</b>\n\n👇 Нажмите кнопку, чтобы играть!", reply_markup=kb, parse_mode="HTML")

# ═══════════════════════════ ЗАПУСК ═══════════════════════════
async def main():
    init_db()
    app = web.Application()
    
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            return web.Response(headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            })
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    
    app.middlewares.append(cors_middleware)
    
    app.router.add_get("/api/data", api_data)
    app.router.add_get("/api/build", api_build)
    app.router.add_get("/api/collect", api_collect)
    app.router.add_get("/api/top", api_top)
    app.router.add_get("/api/raid", api_raid)
    app.router.add_get("/api/tasks", api_tasks)
    app.router.add_get("/api/claim_task", api_claim_task)
    app.router.add_get("/api/prestige", api_prestige)
    app.router.add_get("/api/buy_energy", api_buy_energy)
    app.router.add_get("/api/buy_money", api_buy_money)
    app.router.add_get("/api/buy_shield", api_buy_shield)
    app.router.add_get("/api/buy_vip", api_buy_vip)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 5000)
    await site.start()
    print("API на порту 5000")
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())