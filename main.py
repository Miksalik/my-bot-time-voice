import discord
from discord.ext import commands, tasks
import sqlite3
import time
import os
import re
import asyncio  # Добавлено для безопасных пауз в асинхронных командах

# Настройка намерений (Intents)
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Словарь для отслеживания активных сессий в реальном времени
active_sessions = {}

# === ВАЖНЫЕ НАСТРОЙКИ СЕРВЕРА ===
ADMIN_IDS = [
    595594811239694374, 864117995932090389, 316985657371262988  # ID админов сервера
]
LOG_CHANNEL_ID = 1534155761608032336  # ID текстового канала для статистики и оповещений
# ================================

# Подключение базы данных SQLite
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
os.makedirs(DATA_DIR, exist_ok=True)  # Защита от отсутствия папки на хостинге
db_path = os.path.join(DATA_DIR, 'voice_time.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    total_seconds INTEGER DEFAULT 0
)
""")
conn.commit()
# Геймерская палитра цветов по степени редкости (Hex-коды)
RARITY_COLORS = {
    "COMMON": 0x9d9d9d,       # Обычный (Серый)
    "UNCOMMON": 0x1eff00,     # Необычный (Зеленый)
    "RARE": 0x0070dd,         # Редкий (Синий)
    "EPIC": 0xa335ee,         # Эпический (Фиолетовый)
    "LEGENDARY": 0xff8000,    # Легендарный (Оранжевый)
    "MYTHIC": 0xff4040,       # Мифический (Ярко-красный)
    "ANCIENT": 0xe6cc80,      # Древний / Золотой (Янтарный)
    "IMMORTAL": 0xe5c158      # Бессмертный (Переливчатый золотой)
}

# Сетка статусных ролей с привязанными цветами редкости
HOURS_ROLES = {
    1:    {"name": "🧭 Прохожий", "emoji": "🧭", "color": RARITY_COLORS["COMMON"]},
    5:    {"name": "⛺ Турист", "emoji": "⛺", "color": RARITY_COLORS["COMMON"]},
    10:   {"name": "🎒 Постоялец", "emoji": "🎒", "color": RARITY_COLORS["UNCOMMON"]},
    50:   {"name": "🛡️ Местный", "emoji": "🛡️", "color": RARITY_COLORS["UNCOMMON"]},
    100:  {"name": "⚔️ Завсегдатай", "emoji": "⚔️", "color": RARITY_COLORS["RARE"]},
    150:  {"name": "🏰 Горожанин", "emoji": "🏰", "color": RARITY_COLORS["RARE"]},
    200:  {"name": "🏅 Олдфаг", "emoji": "🏅", "color": RARITY_COLORS["RARE"]},
    300:  {"name": "🔮 Знаток", "emoji": "🔮", "color": RARITY_COLORS["EPIC"]},
    400:  {"name": "📜 Хранитель", "emoji": "📜", "color": RARITY_COLORS["EPIC"]},
    500:  {"name": "🌟 Активист", "emoji": "🌟", "color": RARITY_COLORS["EPIC"]},
    750:  {"name": "💎 Ветеран", "emoji": "💎", "color": RARITY_COLORS["LEGENDARY"]},
    1000: {"name": "👑 Элита сервера", "emoji": "👑", "color": RARITY_COLORS["LEGENDARY"]},
    1250: {"name": "🔱 Магистр чата", "emoji": "🔱", "color": RARITY_COLORS["LEGENDARY"]},
    1500: {"name": "🌌 Небожитель", "emoji": "🌌", "color": RARITY_COLORS["MYTHIC"]},
    1750: {"name": "🌋 Творец истории", "emoji": "🌋", "color": RARITY_COLORS["MYTHIC"]},
    2000: {"name": "🪐 Легенда", "emoji": "🪐", "color": RARITY_COLORS["MYTHIC"]},
    2500: {"name": "⚡ Титан голосовых", "emoji": "⚡", "color": RARITY_COLORS["ANCIENT"]},
    3000: {"name": "🌀 Хранитель Времени", "emoji": "🌀", "color": RARITY_COLORS["ANCIENT"]},
    3500: {"name": "☄️ Вечный", "emoji": "☄️", "color": RARITY_COLORS["ANCIENT"]},
    4000: {"name": "🔮 Абсолют", "emoji": "🔮", "color": RARITY_COLORS["IMMORTAL"]},
    4500: {"name": "⛩️ Патриарх сервера", "emoji": "⛩️", "color": RARITY_COLORS["IMMORTAL"]},
    5000: {"name": "🪐 Повелитель Эфира", "emoji": "🪐", "color": RARITY_COLORS["IMMORTAL"]}
}

def get_new_nickname(current_name, hours, emoji):
    """Начисто стирает любые старые хвосты и возвращает ник со строгим отображением ЧАСОВ"""
    clean_name = re.sub(r'\s*\|\s*\d+ч.*$', '', current_name).strip()
    suffix = f" | {hours}ч{emoji}"
    
    if len(clean_name) + len(suffix) > 32:
        clean_name = clean_name[:32 - len(suffix)]
        
    return f"{clean_name}{suffix}"

def get_role_status_text(hours_int):
    """Возвращает название роли по часам"""
    current_role_name = "🧭 Прохожий"
    for milestone in sorted(HOURS_ROLES.keys()):
        if hours_int >= milestone:
            current_role_name = HOURS_ROLES[milestone]["name"]
    return current_role_name
# Кэш для предотвращения спама поздравлениями в лог-канал
last_promoted_hours = {}

# === ОПТИМИЗИРОВАННЫЙ МЕНЕДЖЕР РОЛЕЙ И НИКНЕЙМОВ ===
async def manage_time_roles(member, total_hours):
    """Управляет выдачей ролей редкости и обновляет никнейм ТОЛЬКО при смене целого часа"""
    hours_int = int(total_hours)
    guild = member.guild
    
    target_milestone = None
    for milestone in sorted(HOURS_ROLES.keys()):
        if hours_int >= milestone:
            target_milestone = milestone
            
    if not target_milestone:
        return

    role_info = HOURS_ROLES[target_milestone]
    target_role_name = role_info["name"]
    role_emoji = role_info["emoji"]
    final_hex = role_info["color"]
    
    # 1. Проверка и выдача роли
    target_role = discord.utils.get(guild.roles, name=target_role_name)
    if not target_role:
        try:
            target_role = await guild.create_role(name=target_role_name, color=discord.Color(final_hex), reason="Ранги")
        except discord.Forbidden:
            return
        
    is_new_role_gained = target_role not in member.roles
    if is_new_role_gained:
        try:
            await member.add_roles(target_role)
        except discord.Forbidden:
            pass

    # Снимаем старые роли активности
    for role in member.roles:
        if ("часов" in role.name or "час" in role.name or any(r["name"] == role.name for r in HOURS_ROLES.values())) and role.name != target_role_name:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

    # 2. УМНОЕ ОБНОВЛЕНИЕ НИКНЕЙМА (Защита от Rate Limit)
    current_display_name = member.display_name
    
    # Проверяем, записан ли уже СЛЕДУЮЩИЙ или ТЕКУЩИЙ правильный час в нике
    # Регулярное выражение ищет хвостик "| количество_часов ч"
    match = re.search(r'\|\s*(\d+)ч', current_display_name)
    
    if match:
        existing_hours = int(match.group(1))
        # ЕСЛИ ЧАСЫ В НИКЕ СОВПАДАЮТ С ЧАСАМИ В БАЗЕ — ИГНОРИРУЕМ И НЕ СПАМИМ ДИСКОРД!
        if existing_hours == hours_int and not is_new_role_gained:
            return

    # Если часы изменились или получили новую роль — генерируем новый ник
    new_nick = get_new_nickname(current_display_name, hours_int, role_emoji)
    
    if current_display_name != new_nick:
        try:
            await member.edit(nick=new_nick)
            print(f"[Успех] Никнейм пользователя {member.name} обновлен до {hours_int}ч.")
        except discord.Forbidden:
            pass
        except discord.HTTPException as e:
            print(f"[Ошибка API] Не удалось обновить ник {member.name}: {e}")

    # 3. Оповещение в лог-канал
    already_notified = last_promoted_hours.get(member.id) == hours_int
    if not already_notified and (is_new_role_gained or (hours_int >= 10 and hours_int % 10 == 0)):
        last_promoted_hours[member.id] = hours_int
        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            if log_channel:
                if hours_int % 10 == 1 and hours_int % 100 != 11:
                    hours_text = "час"
                elif (hours_int % 10 == 2 or hours_int % 10 == 3 or hours_int % 10 == 4) and not (hours_int % 100 == 12 or hours_int % 100 == 13 or hours_int % 100 == 14):
                    hours_text = "часа"
                else:
                    hours_text = "часов"

                embed_lvl = discord.Embed(title="📈 Прогресс активности!", description=f"Преодолена отметка в **{hours_int}** {hours_text}!", color=final_hex)
                embed_lvl.add_field(name="Ранг:", value=target_role.mention)
                if member.avatar:
                    embed_lvl.set_thumbnail(url=member.avatar.url)
                await log_channel.send(f"🎉 Поздравляем {member.mention}!", embed=embed_lvl)
        except:
            pass


# === ЕЖЕМИНУТНЫЙ ФОНОВЫЙ ЦИКЛ С ИСПРАВЛЕННЫМ ВЫЗОВОМ ===
@tasks.loop(seconds=60)
async def check_live_voice_users():
    current_time = int(time.time())
    for user_id, join_time in list(active_sessions.items()):
        duration = current_time - join_time
        if duration <= 0:
            continue
            
        cursor.execute("INSERT OR IGNORE INTO users (user_id, total_seconds) VALUES (?, 0)", (user_id,))
        cursor.execute("UPDATE users SET total_seconds = total_seconds + ? WHERE user_id = ?", [duration, user_id])
        conn.commit()
        
        active_sessions[user_id] = current_time
        
        cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        if res:
            # ИСПРАВЛЕНО: берем первый элемент из кортежа [0]
            total_seconds = res[0]
            total_hours = total_seconds / 3600.0
            
            for guild in bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    # Теперь эта функция не будет спамить каждую минуту!
                    await manage_time_roles(member, total_hours)

@bot.event
async def on_ready():
    print("=========================================")
    print(f"Бот {bot.user} успешно запущен и готов к работе!")
    print(f"Канал для логов и команд установлен на ID: {LOG_CHANNEL_ID}")
    print("=========================================")
    if not check_live_voice_users.is_running():
        check_live_voice_users.start()

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
        
    user_id = member.id
    current_time = int(time.time())
    
    # Сценарий 1: Пользователь зашел в канал или переключился
    if after.channel is not None and (before.channel is None or before.channel.id != after.channel.id):
        active_sessions[user_id] = current_time
        
    # Сценарий 2: Пользователь полностью покинул голосовые каналы
    elif before.channel is not None and after.channel is None:
        if user_id in active_sessions:
            join_time = active_sessions.pop(user_id)
            duration = current_time - join_time
            if duration > 0:
                cursor.execute("INSERT OR IGNORE INTO users (user_id, total_seconds) VALUES (?, 0)", (user_id,))
                cursor.execute("UPDATE users SET total_seconds = total_seconds + ? WHERE user_id = ?", [duration, user_id])
                conn.commit()
@bot.command(name="time")
async def show_voice_time(ctx, target_member: discord.Member = None):
    """Выводит личную статистику или статистику другого человека с точными минутами"""
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send(f"❌ {ctx.author.mention}, эту команду можно использовать только в канале <#{LOG_CHANNEL_ID}>!", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass
        return

    current_time = int(time.time())

    if target_member is not None:
        if ctx.author.id not in ADMIN_IDS:
            await ctx.send(f"❌ {ctx.author.mention}, у вас нет прав просматривать чужую статистику!")
            return
        user_to_check = target_member
        is_checking_self = False
    else:
        user_to_check = ctx.author
        is_checking_self = True

    cursor.execute("SELECT total_seconds FROM users WHERE user_id = ?", (user_to_check.id,))
    result = cursor.fetchone()
    saved_seconds = result[0] if result else 0

    # Плюсуем текущий хвостик онлайн-сессии для идеальной точности до секунды
    if user_to_check.id in active_sessions:
        saved_seconds += (current_time - active_sessions[user_to_check.id])

    if saved_seconds == 0:
        if is_checking_self:
            await ctx.send(f"❌ {ctx.author.mention}, вы еще не сидели в голосовых каналах.")
        else:
            await ctx.send(f"⚠️ Участник {user_to_check.mention} еще не сидел в голосовых каналах.")
        return

    hours = saved_seconds // 3600
    minutes = (saved_seconds % 3600) // 60

    next_milestone_hours = None
    current_role_name = get_role_status_text(hours)
    next_role_name = "Повелитель Эфира (Максимум)"
    
    milestones = sorted(HOURS_ROLES.keys())
    for i, milestone in enumerate(milestones):
        if hours >= milestone:
            if i + 1 < len(milestones):
                next_milestone_hours = milestones[i + 1]
                next_role_name = HOURS_ROLES[next_milestone_hours]["name"]
        else:
            if next_milestone_hours is None:
                next_milestone_hours = milestones[0]
                next_role_name = HOURS_ROLES[next_milestone_hours]["name"]
            break

    title_text = "📊 Ваша голосовая активность" if is_checking_self else f"📊 Активность: {user_to_check.display_name}"
    embed = discord.Embed(title=title_text, color=0x0070dd)
    embed.add_field(name="⏳ Наиграно времени:", value=f"**{hours}** ч. **{minutes}** мин.", inline=False)
    embed.add_field(name="🛡️ Текущий ранг:", value=f"**{current_role_name}**", inline=True)

    if next_milestone_hours and hours < 5000:
        remaining_seconds = (next_milestone_hours * 3600) - saved_seconds
        rem_hours = remaining_seconds // 3600
        rem_minutes = (remaining_seconds % 3600) // 60
        embed.add_field(
            name="🎯 До следующей роли:", 
            value=f"Осталось **{rem_hours}** ч. **{rem_minutes}** мин. (до **{next_role_name}** на {next_milestone_hours} ч.)", 
            inline=False
        )
    else:
        embed.add_field(name="Статус:", value="Максимальный уровень активности достигнут!", inline=False)

    embed.set_footer(text=f"Запросил: {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)


@bot.command(name="top")
async def show_top_users(ctx):
    """Выводит актуальный топ-10 активных пользователей сервера"""
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send(f"❌ {ctx.author.mention}, эту команду можно использовать только в канале <#{LOG_CHANNEL_ID}>!", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass
        return

    current_time = int(time.time())

    cursor.execute("SELECT user_id, total_seconds FROM users")
    db_users = cursor.fetchall()
    all_users = {user_id: total_seconds for user_id, total_seconds in db_users}

    for user_id, join_time in active_sessions.items():
        session_duration = current_time - join_time
        if user_id in all_users:
            all_users[user_id] += session_duration
        else:
            all_users[user_id] = session_duration

    if not all_users:
        await ctx.send("📊 Список лидеров пока пуст!")
        return

    # Исправленная точная сортировка словаря по секундам
    sorted_top = sorted(all_users.items(), key=lambda item: item[1], reverse=True)[:10]

    embed = discord.Embed(title="🏆 ТОП-10 Активных в Голосовых Каналах", color=0xb6960d)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    leaderboard_text = ""

    for index, (user_id, total_seconds) in enumerate(sorted_top):
        member = ctx.guild.get_member(user_id)
        if not member:
            try:
                member = await ctx.guild.fetch_member(user_id)
            except:
                pass
                
        name = member.mention if member else f"Участник [{user_id}]"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        user_status = get_role_status_text(hours)
        leaderboard_text += f"{medals[index]} {name} — **{hours}** ч. **{minutes}** мин. ({user_status})\n"

    embed.description = leaderboard_text
    await ctx.send(embed=embed)
class LeaderboardPaginator(discord.ui.View):
    def __init__(self, pages, total_pages):
        super().__init__(timeout=60)
        self.pages = pages
        self.total_pages = total_pages
        self.current_page = 0
        self.message = None
        self.update_button_states()

    def update_button_states(self):
        self.prev_page_btn.disabled = self.current_page == 0
        self.next_page_btn.disabled = self.current_page == self.total_pages - 1

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except:
                pass

    @discord.ui.button(label="◀ Назад", style=discord.ButtonStyle.primary)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_button_states()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Вперед ▶", style=discord.ButtonStyle.primary)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_button_states()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)


@bot.command(name="top_full")
async def show_full_leaderboard(ctx):
    """Выводит полный список абсолютно всех пользователей из базы данных по 20 человек"""
    if ctx.channel.id != LOG_CHANNEL_ID and ctx.author.id not in ADMIN_IDS:
        await ctx.send(f"❌ {ctx.author.mention}, эту команду можно использовать только в канале <#{LOG_CHANNEL_ID}>!", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass
        return

    current_time = int(time.time())

    cursor.execute("SELECT user_id, total_seconds FROM users")
    db_users = cursor.fetchall()
    all_users = {user_id: total_seconds for user_id, total_seconds in db_users}

    for user_id, join_time in active_sessions.items():
        session_duration = current_time - join_time
        if user_id in all_users:
            all_users[user_id] += session_duration
        else:
            all_users[user_id] = session_duration

    if not all_users:
        await ctx.send("📊 База данных активности пуста!")
        return

    sorted_users = sorted(all_users.items(), key=lambda item: item[1], reverse=True)
    
    per_page = 20
    user_chunks = [sorted_users[i:i + per_page] for i in range(0, len(sorted_users), per_page)]
    total_pages = len(user_chunks)
    
    embeds = []
    
    for page_index, chunk in enumerate(user_chunks):
        embed = discord.Embed(title="📋 Полный список лидеров голосовых каналов", color=0x2b2d31)
        leaderboard_text = ""
        
        for index, (user_id, total_seconds) in enumerate(chunk):
            global_index = page_index * per_page + index + 1
            
            member = ctx.guild.get_member(user_id)
            if not member:
                try:
                    member = await ctx.guild.fetch_member(user_id)
                except:
                    pass
            
            name = member.mention if member else f"Участник [{user_id}]"
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            user_status = get_role_status_text(hours)
            
            leaderboard_text += f"`#{global_index:02d}` {name} — **{hours}** ч. **{minutes}** мин. ({user_status})\n"
            
        embed.description = leaderboard_text
        embed.set_footer(text=f"Страница {page_index + 1} из {total_pages} • Всего участников: {len(sorted_users)}")
        embeds.append(embed)

    if total_pages == 1:
        await ctx.send(embed=embeds[0])
    else:
        view = LeaderboardPaginator(embeds, total_pages)
        view.message = await ctx.send(embed=embeds[0], view=view)
@bot.command(name="sync")
async def sync_old_database(ctx):
    """Синхронизирует ники и роли всем игрокам на основе старой базы данных"""
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ У вас нет прав для использования этой команды.")
        return

    status_message = await ctx.send("⏳ Начинаю полную синхронизацию старой базы данных по системе редкости рангов...")
    
    cursor.execute("SELECT user_id, total_seconds FROM users")
    all_users = cursor.fetchall()
    
    total_users_count = len(all_users)
    success_count = 0
    
    for index, (user_id, total_seconds) in enumerate(all_users):
        member = ctx.guild.get_member(user_id)
        if not member:
            try:
                member = await ctx.guild.fetch_member(user_id)
            except:
                continue
                
        if member:
            try:
                await manage_time_roles(member, total_seconds / 3600.0)
                success_count += 1
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"Ошибка при синхронизации пользователя {user_id}: {e}")
            
            # Асинхронная безопасная пауза против блокировок со стороны API Дискорда
            await asyncio.sleep(0.5)
            
        if index % 15 == 0 and index > 0:
            try:
                await status_message.edit(content=f"⏳ Синхронизация в процессе... Обработано {index}/{total_users_count} аккаунтов.")
            except:
                pass
            
    await ctx.send(f"✅ Синхронизация успешно завершена! Успешно обновлено профилей: **{success_count}** из **{total_users_count}**.")


# Безопасный запуск бота через переменную среды хостинга
token = os.getenv("BOT_TOKEN")
if token:
    bot.run(token)
else:
    print("Ошибка: Переменная BOT_TOKEN не настроена в панели хостинга!")
