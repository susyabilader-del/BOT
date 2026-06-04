"""Veritabanindaki mesajlari parser'dan gecirip dogrulama yap."""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from database import init_db, get_messages_by_group
from parser import MessageParser, IslemTipi
from datetime import datetime, timedelta

async def test():
    await init_db()
    parser = MessageParser()

    since = (datetime.now() - timedelta(days=7)).isoformat()
    source_msgs = await get_messages_by_group("source", since_date=since, limit=2500)
    verify_msgs = await get_messages_by_group("verify", since_date=since, limit=500)

    print(f"Kaynak mesajlari: {len(source_msgs)}")
    print(f"Teyid mesajlari: {len(verify_msgs)}")
    print("=" * 60)

    # Parse et ve anlamli olanlari goster
    structured_count = 0
    kt_count = 0
    iptal_count = 0
    onay_count = 0
    hash_count = 0
    odeme_count = 0
    parsed_with_id = 0

    all_parsed = []

    for msg in source_msgs + verify_msgs:
        parsed = parser.parse(msg["text"])
        
        if parsed.is_structured:
            structured_count += 1
        if parsed.musteri_id:
            parsed_with_id += 1
        if parsed.islem_hash:
            hash_count += 1
        if parsed.islem_tipi == IslemTipi.CEKIM_IPTAL:
            iptal_count += 1
        if parsed.islem_tipi == IslemTipi.ONAY:
            onay_count += 1
        if parsed.islem_tipi == IslemTipi.KT:
            kt_count += 1
        if parsed.islem_tipi == IslemTipi.ODEME:
            odeme_count += 1

        if parsed.islem_tipi != IslemTipi.BILINMIYOR or parsed.musteri_id or parsed.tutar:
            all_parsed.append((msg, parsed))

    print(f"\nPARSE ISTATISTIKLERI:")
    print(f"  Yapılandırılmış blok: {structured_count}")
    print(f"  Müşteri ID'li: {parsed_with_id}")
    print(f"  Hash: {hash_count}")
    print(f"  Çekim iptal: {iptal_count}")
    print(f"  Onay: {onay_count}")
    print(f"  Ödeme: {odeme_count}")
    print(f"  KT: {kt_count}")
    print(f"  Anlamlı parse: {len(all_parsed)} / {len(source_msgs) + len(verify_msgs)}")

    # Yapılandırılmış blokları göster
    print("\n" + "=" * 60)
    print("YAPILANDIRILMIS BLOKLAR (ilk 5):")
    print("=" * 60)
    shown = 0
    for msg, parsed in all_parsed:
        if parsed.is_structured and shown < 5:
            print(f"\n  [{msg['date'][:16]}] Grup: {msg['group_id']}")
            print(f"  İsim: {parsed.musteri_adi}")
            print(f"  ID: {parsed.musteri_id}")
            print(f"  IBAN: {parsed.iban}")
            print(f"  Tutar: {parsed.tutar} ({parsed.tutar_yonu})")
            print(f"  Durum: {parsed.durum}")
            print(f"  İşlem: {parsed.islem_tipi.value}")
            print(f"  Talep: {parsed.talep_tarihi}")
            print("  ---")
            shown += 1

    # Çekim iptal mesajlarını göster
    print("\n" + "=" * 60)
    print("CEKIM IPTAL MESAJLARI:")
    print("=" * 60)
    for msg, parsed in all_parsed:
        if parsed.islem_tipi == IslemTipi.CEKIM_IPTAL:
            print(f"  [{msg['date'][:16]}] {parsed.musteri_adi or '?'} | ID: {parsed.musteri_id or '?'} | ₺{parsed.tutar or '?'}")

    # Müşteri ID bazlı eşleştirme
    print("\n" + "=" * 60)
    print("MUSTERI ID ESLESTIRME:")
    print("=" * 60)
    by_id = {}
    for msg, parsed in all_parsed:
        if parsed.musteri_id:
            by_id.setdefault(parsed.musteri_id, []).append((msg, parsed))

    for mid, items in by_id.items():
        if len(items) > 1:
            groups = set(m["group_id"] for m, p in items)
            if len(groups) > 1:  # Farklı gruplarda görünüyor
                print(f"\n  ID: {mid} ({len(items)} mesaj, {len(groups)} grup)")
                for m, p in items:
                    print(f"    [{m['date'][:16]}] Grup:{m['group_id'][-4:]} | {p.islem_tipi.value} | {p.musteri_adi} | ₺{p.tutar or '-'}")

asyncio.run(test())
