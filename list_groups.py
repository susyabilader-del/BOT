"""Pyrogram ile kullanıcının tüm sohbetlerini listeler. Grup ID'lerini bulmak için kullanılır."""

import asyncio
import os
from pyrogram import Client
from pyrogram.enums import ChatType
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")


async def main():
    os.makedirs("data", exist_ok=True)

    async with Client("verifier_session", api_id=API_ID, api_hash=API_HASH, workdir="data") as app:
        print("\n" + "="*60)
        print("  TÜM SOHBETLER (Gruplar + Kanallar + Arşiv)")
        print("="*60 + "\n")

        all_chats = []

        # Normal diyaloglar
        print("  [Normal Sohbetler]")
        async for dialog in app.get_dialogs():
            chat = dialog.chat
            chat_type = str(chat.type).split(".")[-1]
            if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
                all_chats.append(chat)
                print(f"    • {chat.title}  [ID: {chat.id}]  ({chat_type})")

        # Arşivli sohbetler
        print("\n  [Arşivli Sohbetler]")
        try:
            async for dialog in app.get_dialogs(folder_id=1):
                chat = dialog.chat
                chat_type = str(chat.type).split(".")[-1]
                if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
                    if chat.id not in [c.id for c in all_chats]:
                        all_chats.append(chat)
                    print(f"    • {chat.title}  [ID: {chat.id}]  ({chat_type})")
        except Exception as e:
            print(f"    (arşiv okunamadı: {e})")

        print("\n" + "="*60)
        if all_chats:
            print(f"\n  Toplam {len(all_chats)} grup/kanal bulundu.\n")
            print("  Kaynak ve doğrulama grubunun ID'lerini kopyalayın.")
        else:
            print("\n  Hiç grup/kanal bulunamadı.")
            print("  Bu hesabın üye olduğu gruplar yok olabilir.")
            print("  Farklı bir hesap deneyin veya grup ID'lerini")
            print("  @RawDataBot ile öğrenin.")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
