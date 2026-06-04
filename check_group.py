"""Grup erişim testi."""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pyrogram import Client
from config import Config

async def test():
    client = Client('verifier_session', api_id=Config.API_ID, api_hash=Config.API_HASH, workdir='data')
    await client.start()

    groups = [
        (-4922606361, "ALL HAVALE RUSSPAYMENT YATIRIM DESTEK"),
        (-5203715492, "ALL HAVALE RUSSPAYMENT CEKIM DESTEK"),
        (-5148876334, "Payzone-2misli Cekim Operasyon"),
    ]

    for gid, name in groups:
        print(f'\n{"="*60}')
        print(f'{name} (ID: {gid})')
        print(f'{"="*60}')
        count = 0
        try:
            async for msg in client.get_chat_history(gid, limit=5):
                count += 1
                text = msg.text or msg.caption or ""
                sender = msg.from_user.username if msg.from_user else "?"
                if text:
                    print(f'  [{msg.date}] @{sender}: {text[:120]}')
                elif msg.photo:
                    print(f'  [{msg.date}] @{sender}: [FOTO]')
                else:
                    print(f'  [{msg.date}] @{sender}: [service/other]')
            print(f'  -> {count} mesaj goruldu')
        except Exception as e:
            print(f'  HATA: {e}')

    await client.stop()

asyncio.run(test())
