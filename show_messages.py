"""Veritabanindaki mesajlari incele."""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
import aiosqlite

async def show():
    db = await aiosqlite.connect('data/verifier.db')
    db.row_factory = aiosqlite.Row

    # 2 Haziran mesajlari
    cursor = await db.execute(
        "SELECT group_id, text, date, username FROM messages "
        "WHERE date LIKE '2026-06-02%' ORDER BY date DESC LIMIT 20"
    )
    rows = await cursor.fetchall()
    print("=== 2 HAZIRAN MESAJLARI ===")
    print(f"Bulunan: {len(rows)} mesaj\n")
    for r in rows:
        print(f"[{r['date']}] @{r['username']}:")
        print(f"  {r['text'][:200]}")
        print("---")

    # Genel kaynak ornekleri
    cursor2 = await db.execute(
        "SELECT group_id, text, date, username FROM messages "
        "WHERE group_type='source' ORDER BY date DESC LIMIT 15"
    )
    rows2 = await cursor2.fetchall()
    print("\n=== SON KAYNAK MESAJLARI ===")
    for r in rows2:
        print(f"[{r['date']}] @{r['username']}:")
        print(f"  {r['text'][:200]}")
        print("---")

    # Verify grubundan ornekler
    cursor3 = await db.execute(
        "SELECT group_id, text, date, username FROM messages "
        "WHERE group_type='verify' ORDER BY date DESC LIMIT 10"
    )
    rows3 = await cursor3.fetchall()
    print("\n=== TEYiD GRUBU MESAJLARI ===")
    for r in rows3:
        print(f"[{r['date']}] @{r['username']}:")
        print(f"  {r['text'][:200]}")
        print("---")

    # Istatistik
    cursor4 = await db.execute(
        "SELECT date(date) as d, COUNT(*) as c FROM messages GROUP BY date(date) ORDER BY d"
    )
    rows4 = await cursor4.fetchall()
    print("\n=== GUN BAZLI ISTATISTIK ===")
    for r in rows4:
        print(f"  {r['d']}: {r['c']} mesaj")

    await db.close()

asyncio.run(show())
