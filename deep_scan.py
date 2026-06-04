"""Son 24 saatlik mesajları tüm gruplardan çeken derin tarama scripti."""

import asyncio
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')

from datetime import datetime, timedelta
from pyrogram import Client
from config import Config
from database import init_db, save_message, update_scan_state

async def deep_scan():
    print("=" * 60)
    print("DERIN TARAMA - Son 7 Gun")
    print("=" * 60)

    await init_db()

    client = Client(
        "verifier_session",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        workdir="data"
    )

    await client.start()
    print("\nPyrogram baglandi.\n")

    cutoff = datetime.now() - timedelta(days=7)
    total_messages = 0
    group_stats = []

    # Tum kaynak gruplari tara
    source_groups = Config.get_source_groups()
    verify_groups = Config.get_verify_groups()

    print(f"Kaynak gruplari: {len(source_groups)}")
    print(f"Teyid gruplari: {len(verify_groups)}")
    print("-" * 60)

    all_groups = [(gid, "source") for gid in source_groups] + [(gid, "verify") for gid in verify_groups]

    for group_id, group_type in all_groups:
        chat_id = int(group_id)
        count = 0
        max_msg_id = 0

        try:
            # Grup bilgisi
            chat = await client.get_chat(chat_id)
            group_name = chat.title or str(chat_id)
            print(f"\n[{group_type.upper()}] {group_name} ({group_id})")

            async for message in client.get_chat_history(chat_id, limit=3000):
                # 24 saatten eski mesajlari atla
                if message.date and message.date < cutoff:
                    break

                text = message.text or message.caption or ""
                if not text.strip():
                    continue

                user_id = message.from_user.id if message.from_user else None
                username = message.from_user.username if message.from_user else None

                await save_message(
                    group_id=group_id,
                    group_type=group_type,
                    message_id=message.id,
                    user_id=user_id,
                    username=username,
                    text=text,
                    date=message.date.isoformat()
                )

                max_msg_id = max(max_msg_id, message.id)
                count += 1

            if max_msg_id > 0:
                await update_scan_state(group_id, max_msg_id)

            print(f"  -> {count} mesaj kaydedildi")
            group_stats.append((group_name, group_type, count))
            total_messages += count

        except Exception as e:
            print(f"  -> HATA: {e}")
            group_stats.append((str(group_id), group_type, f"HATA: {e}"))

        # Rate limit - gruplar arasi kisa bekleme
        await asyncio.sleep(1)

    await client.stop()

    # Ozet
    print("\n" + "=" * 60)
    print("TARAMA OZETI")
    print("=" * 60)
    print(f"\nToplam: {total_messages} mesaj kaydedildi")
    print(f"Taranan grup: {len(all_groups)}")
    print(f"\nDetay:")
    for name, gtype, cnt in group_stats:
        icon = "BAYi" if gtype == "source" else "TEYiD"
        print(f"  [{icon}] {name}: {cnt}")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(deep_scan())
