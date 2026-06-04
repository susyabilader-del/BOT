"""API response formatini incele."""
import asyncio
import sys
import json
sys.stdout.reconfigure(encoding='utf-8')
from api_client import RussPaymentAPI
from datetime import date, timedelta

async def test():
    api = RussPaymentAPI()

    # Bugünün işlemlerini çek
    for day_offset in range(0, 3):
        target = date.today() - timedelta(days=day_offset)
        print(f"\n{'='*60}")
        print(f"TARİH: {target}")
        print(f"{'='*60}")
        try:
            txs = await api.get_transactions(target_date=target, limit=5)
            if not txs:
                print("  (boş)")
                continue

            if isinstance(txs, list) and len(txs) > 0:
                # İlk işlemi detaylı göster
                print(f"  Toplam: {len(txs)} işlem")
                print(f"\n  ÖRNEK İŞLEM (ilk):")
                print(json.dumps(txs[0], indent=4, ensure_ascii=False, default=str))

                # Tüm alanları listele
                print(f"\n  ALAN İSİMLERİ: {list(txs[0].keys())}")

                # İkinci işlemi de göster
                if len(txs) > 1:
                    print(f"\n  İKİNCİ İŞLEM:")
                    print(json.dumps(txs[1], indent=4, ensure_ascii=False, default=str))
            elif isinstance(txs, dict):
                print(json.dumps(txs, indent=4, ensure_ascii=False, default=str))
        except Exception as e:
            print(f"  HATA: {e}")

asyncio.run(test())
