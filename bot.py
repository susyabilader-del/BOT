import asyncio
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from config import Config
from database import add_rule, get_rules, get_recent_verifications, get_verification_stats
from verifier import VerificationEngine
from scanner import GroupScanner
import logging

logger = logging.getLogger(__name__)


class VerifierBot:
    def __init__(self, scanner: GroupScanner, verifier: VerificationEngine):
        self.scanner = scanner
        self.verifier = verifier
        self.app = None

    def _is_admin(self, user_id: int) -> bool:
        return user_id == Config.ADMIN_USER_ID

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok.")
            return

        await update.message.reply_text(
            "🔍 **Ödeme Doğrulama Botu**\n\n"
            "**🚨 Tespit:**\n"
            "/verify - Tam doğrulama (kritik çelişkiler)\n"
            "/tutarsiz - Sadece çelişki/tutarsızlıklar\n\n"
            "**🔎 Sorgulama:**\n"
            "/cekim - Çekim işlemleri (iptal/bekleyen)\n"
            "/yatirim - Yatırım işlemleri\n"
            "/musteri <isim/ID> - Müşteri detay\n"
            "/tarih <GG.AA> - Tarihe göre sorgula\n"
            "/search <metin> - Gruplarda ara\n\n"
            "**📊 Genel:**\n"
            "/scan - Grupları tara\n"
            "/report - Rapor göster\n"
            "/api geciken - API geciken işlemler\n"
            "/status - Bot durumu",
            parse_mode="Markdown"
        )

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        msg = await update.message.reply_text("🔄 Gruplar taranıyor...")

        try:
            results = await self.scanner.scan_all_groups()
            text = "✅ **Tarama Tamamlandı**\n\n"
            text += f"� Bayi grupları: {results.get('source', 0)} yeni mesaj ({results.get('source_groups', 0)} grup)\n"
            text += f"📥 Teyid grupları: {results.get('verify', 0)} yeni mesaj ({results.get('verify_groups', 0)} grup)"
            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Tarama hatası: {e}")

    async def cmd_verify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        msg = await update.message.reply_text("🔍 Doğrulama çalıştırılıyor...")

        try:
            result = await self.verifier.run_verification()
            issues = result.get("issues", [])
            rule_results = result.get("rule_results", [])
            total_src = result.get("total_source", 0)
            total_ver = result.get("total_verify", 0)

            # SADECE KRİTİK çelişkileri filtrele
            critical_types = {"IPTAL_AMA_ODENMIS", "ONAY_AMA_RED", "ODENMIS_AMA_RED",
                            "TUTAR_UYUSMAZLIGI", "API_RED_GRUP_ONAY", "API_ONAY_GRUP_IPTAL"}
            critical_issues = [i for i in issues if i.get("type") in critical_types]
            critical_rules = [r for r in rule_results if r.get("status") == "inconsistent"]

            # Onaylananlar
            confirmed = [r for r in rule_results if r.get("status") == "confirmed"]

            text = f"✅ **Doğrulama Tamamlandı**\n"
            text += f"📤 Bayi: {total_src} | 📥 Teyid: {total_ver} mesaj\n\n"

            # Kritik çelişkiler (önemli olanlar)
            all_critical = critical_issues + critical_rules
            if all_critical:
                text += f"� **{len(all_critical)} KRİTİK ÇELİŞKİ:**\n"
                for item in all_critical[:8]:
                    if "message" in item:
                        text += f"  🔴 {item['message'][:100]}\n"
                    else:
                        text += f"  🔴 [{item.get('rule_name','')}] {item.get('details','')[:100]}\n"
                if len(all_critical) > 8:
                    text += f"\n  → /tutarsiz ile tümünü gör\n"
            else:
                text += "✅ Kritik çelişki yok!\n"

            # Özet istatistik
            text += f"\n📊 **Özet:**\n"
            text += f"  ✅ Onaylı eşleşme: {len(confirmed)}\n"
            text += f"  🔴 Kritik çelişki: {len(all_critical)}\n"
            text += f"  📋 Toplam kural eşleşmesi: {len(rule_results)}\n"

            # Navigasyon
            text += "\nℹ️ /cekim | /yatirim | /tutarsiz | /musteri <isim>"

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Doğrulama hatası: {e}", exc_info=True)
            await msg.edit_text(f"❌ Doğrulama hatası: {e}")

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        try:
            report = await self.verifier.get_report()
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Rapor hatası: {e}")

    async def cmd_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        rules = await get_rules(active_only=False)
        if not rules:
            await update.message.reply_text("ℹ️ Henüz kural tanımlanmamış.\n/addrule ile ekleyebilirsiniz.")
            return

        text = "📋 **Doğrulama Kuralları:**\n\n"
        for r in rules:
            active = "✅" if r["is_active"] else "❌"
            text += f"{active} **{r['name']}** [{r['rule_type']}]\n"
            text += f"   Kaynak: `{r['source_pattern']}`\n"
            if r["verify_pattern"]:
                text += f"   Doğrulama: `{r['verify_pattern']}`\n"
            text += "\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_addrule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        args = context.args
        if not args or len(args) < 3:
            await update.message.reply_text(
                "📝 **Kural Ekleme Formatı:**\n\n"
                "`/addrule <isim> <tip> <kaynak_pattern> [doğrulama_pattern]`\n\n"
                "**Tipler:**\n"
                "• `keyword` - Anahtar kelime eşleşmesi\n"
                "• `pattern` - Regex pattern eşleşmesi\n"
                "• `user_claim` - Kullanıcı iddia doğrulama\n"
                "• `amount` - Tutar/miktar doğrulama\n"
                "• `custom` - Fuzzy matching\n\n"
                "**Örnekler:**\n"
                "`/addrule odeme_kontrol user_claim ödeme|transfer|gönder`\n"
                "`/addrule fiyat_check amount \\d+\\s*(TL|USD|EUR)`\n"
                "`/addrule trade_verify keyword alım|satım|trade`",
                parse_mode="Markdown"
            )
            return

        name = args[0]
        rule_type = args[1]
        source_pattern = args[2]
        verify_pattern = args[3] if len(args) > 3 else None

        valid_types = ["keyword", "pattern", "user_claim", "amount", "custom"]
        if rule_type not in valid_types:
            await update.message.reply_text(f"❌ Geçersiz tip. Geçerli tipler: {', '.join(valid_types)}")
            return

        try:
            await add_rule(name, rule_type, source_pattern, verify_pattern)
            await update.message.reply_text(f"✅ Kural eklendi: **{name}** [{rule_type}]", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Kural ekleme hatası: {e}")

    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text("Kullanım: `/search <aranacak metin>`", parse_mode="Markdown")
            return

        msg = await update.message.reply_text(f"🔍 '{query}' aranıyor...")

        try:
            source_results = []
            verify_results = []

            # Tüm kaynak gruplarda ara
            for gid in Config.get_source_groups():
                results = await self.scanner.search_messages(gid, query, limit=5)
                source_results.extend(results)

            # Tüm doğrulama gruplarda ara
            for gid in Config.get_verify_groups():
                results = await self.scanner.search_messages(gid, query, limit=5)
                verify_results.extend(results)

            text = f"🔍 **Arama Sonuçları:** '{query}'\n\n"

            if source_results:
                text += f"**📤 Bayi Grupları ({len(source_results)} sonuç):**\n"
                for r in source_results[:5]:
                    preview = r["text"][:80]
                    text += f"  • @{r['username'] or 'anonim'}: {preview}\n"
                text += "\n"

            if verify_results:
                text += f"**📥 Teyid Grupları ({len(verify_results)} sonuç):**\n"
                for r in verify_results[:5]:
                    preview = r["text"][:80]
                    text += f"  • @{r['username'] or 'anonim'}: {preview}\n"

            if not source_results and not verify_results:
                text = f"ℹ️ '{query}' için sonuç bulunamadı."

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Arama hatası: {e}")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        try:
            source_info = await self.scanner.get_group_info(Config.SOURCE_GROUP)
            verify_info = await self.scanner.get_group_info(Config.VERIFY_GROUP)
            stats = await get_verification_stats()

            text = "📡 **Bot Durumu**\n\n"
            text += "**Gruplar:**\n"
            if source_info:
                text += f"  📤 Kaynak: {source_info['title']} ({source_info['members_count']} üye)\n"
            if verify_info:
                text += f"  📥 Doğrulama: {verify_info['title']} ({verify_info['members_count']} üye)\n"

            text += f"\n**Tarama Aralığı:** {Config.SCAN_INTERVAL} dk\n"
            text += f"**Eşleşme Eşiği:** {Config.MATCH_THRESHOLD}%\n"

            total = sum(stats.values()) if stats else 0
            text += f"\n**Toplam Doğrulama:** {total}"

            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Durum hatası: {e}")

    async def cmd_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """API işlem durumu sorgulama."""
        if not self._is_admin(update.effective_user.id):
            return

        if not Config.PAYMENT_API_KEY:
            await update.message.reply_text("⚠️ Payment API yapılandırılmamış.")
            return

        from api_client import RussPaymentAPI
        api = RussPaymentAPI()

        sub_cmd = context.args[0] if context.args else "durum"

        if sub_cmd == "geciken":
            msg = await update.message.reply_text("🔍 Geciken işlemler kontrol ediliyor...")
            try:
                delayed = await api.get_delayed_transactions(max_age_minutes=Config.DELAY_THRESHOLD_MINUTES)
                if not delayed:
                    await msg.edit_text("✅ Geciken işlem yok.")
                    return
                text = f"⚠️ **{len(delayed)} Geciken İşlem ({Config.DELAY_THRESHOLD_MINUTES}+ dk):**\n\n"
                for tx in delayed[:10]:
                    tx_id = tx.get("transactionId") or tx.get("id", "?")
                    name = tx.get("playerFullName") or "?"
                    amount = tx.get("amount", "?")
                    age = tx.get("_age_minutes", "?")
                    text += f"  • `{tx_id}` | {name} | ₺{amount} | {age} dk\n"
                if len(delayed) > 10:
                    text += f"\n... ve {len(delayed) - 10} daha"
                await msg.edit_text(text, parse_mode="Markdown")
            except Exception as e:
                await msg.edit_text(f"❌ API hatası: {e}")

        elif sub_cmd == "islemler":
            msg = await update.message.reply_text("🔍 Bugünkü işlemler çekiliyor...")
            try:
                txs = await api.get_transactions()
                if not txs:
                    await msg.edit_text("ℹ️ Bugün işlem bulunamadı.")
                    return
                approved = sum(1 for t in txs if (t.get("status") or "").upper() == "APPROVED")
                rejected = sum(1 for t in txs if (t.get("status") or "").upper() == "REJECTED")
                pending = len(txs) - approved - rejected
                text = f"📊 **Bugünkü İşlemler ({len(txs)} toplam):**\n\n"
                text += f"  ✅ Onaylı: {approved}\n"
                text += f"  ❌ Red: {rejected}\n"
                text += f"  ⏳ Bekleyen: {pending}\n"
                await msg.edit_text(text, parse_mode="Markdown")
            except Exception as e:
                await msg.edit_text(f"❌ API hatası: {e}")

        else:
            await update.message.reply_text(
                "📡 **API Komutları:**\n\n"
                "`/api geciken` — Geciken işlemleri listele\n"
                "`/api islemler` — Bugünkü işlem özeti\n",
                parse_mode="Markdown"
            )

    async def cmd_musteri(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Müşteri bazlı işlem sorgulama."""
        if not self._is_admin(update.effective_user.id):
            return

        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text(
                "Kullanım: `/musteri <isim veya ID>`\n"
                "Örnek: `/musteri mediha tekgöz`",
                parse_mode="Markdown"
            )
            return

        msg = await update.message.reply_text(f"🔍 '{query}' sorgulanıyor...")

        try:
            detail = await self.verifier.get_transaction_detail(query)
            await msg.edit_text(detail, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Sorgulama hatası: {e}")

    async def cmd_tutarsizlik(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sadece kritik tutarsızlıkları listele."""
        if not self._is_admin(update.effective_user.id):
            return

        try:
            issues = self.verifier.tracker.get_all_inconsistencies()
            # Sadece kritik olanları göster (DOGRULAMA_YOK ve UZUN_BEKLEME hariç)
            critical_types = {"IPTAL_AMA_ODENMIS", "ONAY_AMA_RED", "ODENMIS_AMA_RED", "TUTAR_UYUSMAZLIGI"}
            filtered = [i for i in issues if i.get("type") in critical_types]

            if not filtered:
                # Warning seviyesini de göster
                filtered = [i for i in issues if i.get("severity") in ("critical", "warning")
                           and i.get("type") != "DOGRULAMA_YOK"]

            if not filtered:
                await update.message.reply_text("✅ Kritik tutarsızlık bulunamadı.")
                return

            text = f"� **{len(filtered)} Tutarsızlık:**\n\n"
            for i, issue in enumerate(filtered[:15], 1):
                icon = {"critical": "🔴", "warning": "⚠️", "info": "ℹ️"}.get(issue["severity"], "❓")
                text += f"{i}. {icon} **{issue['type']}**\n"
                text += f"   {issue['message'][:120]}\n\n"

            if len(filtered) > 15:
                text += f"... ve {len(filtered) - 15} daha"

            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {e}")

    async def cmd_cekim(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Çekim işlemlerini listele - iptal, bekleyen, onaylı."""
        if not self._is_admin(update.effective_user.id):
            return

        from parser import MessageParser, IslemTipi
        from database import get_messages_by_group
        from datetime import datetime, timedelta

        msg = await update.message.reply_text("🔍 Çekim işlemleri taranıyor...")

        try:
            parser = MessageParser()
            since = (datetime.now() - timedelta(days=7)).isoformat()
            messages = await get_messages_by_group("source", since_date=since, limit=3000)
            verify_msgs = await get_messages_by_group("verify", since_date=since, limit=3000)

            cekimler = []
            for m in messages + verify_msgs:
                p = parser.parse(m["text"])
                if p.tutar_yonu == "cekim" or p.islem_tipi in (IslemTipi.CEKIM_TALEBI, IslemTipi.CEKIM_IPTAL):
                    cekimler.append({
                        "isim": p.musteri_adi or "?",
                        "id": p.musteri_id or "",
                        "tutar": p.tutar,
                        "durum": p.durum or p.islem_tipi.value,
                        "tarih": m["date"][:16],
                        "grup": "Bayi" if m["group_type"] == "source" else "Teyid"
                    })

            if not cekimler:
                await msg.edit_text("ℹ️ Son 7 günde çekim işlemi bulunamadı.")
                return

            # İptal olanları önce göster
            iptal = [c for c in cekimler if "iptal" in c["durum"]]
            bekleyen = [c for c in cekimler if c["durum"] in ("bekleyen", "beklemede", "cekim_talebi")]
            diger = [c for c in cekimler if c not in iptal and c not in bekleyen]

            text = f"💸 **Çekim İşlemleri** (son 7 gün)\n\n"

            if iptal:
                text += f"🚫 **İPTAL ({len(iptal)}):**\n"
                for c in iptal[:5]:
                    text += f"  • {c['isim']} | ₺{c['tutar'] or '?'} | {c['tarih']}\n"
                text += "\n"

            if bekleyen:
                text += f"⏳ **BEKLEYEN ({len(bekleyen)}):**\n"
                for c in bekleyen[:5]:
                    text += f"  • {c['isim']} | ₺{c['tutar'] or '?'} | {c['tarih']}\n"
                text += "\n"

            text += f"📊 Toplam: {len(cekimler)} çekim | {len(iptal)} iptal | {len(bekleyen)} bekleyen"

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Hata: {e}")

    async def cmd_yatirim(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yatırım işlemlerini listele."""
        if not self._is_admin(update.effective_user.id):
            return

        from parser import MessageParser, IslemTipi
        from database import get_messages_by_group
        from datetime import datetime, timedelta

        msg = await update.message.reply_text("🔍 Yatırım işlemleri taranıyor...")

        try:
            parser = MessageParser()
            since = (datetime.now() - timedelta(days=7)).isoformat()
            messages = await get_messages_by_group("verify", since_date=since, limit=3000)

            yatirimlar = []
            for m in messages:
                p = parser.parse(m["text"])
                if p.tutar_yonu == "yatirim" or (p.tutar and p.is_structured and p.tutar_yonu != "cekim"):
                    yatirimlar.append({
                        "isim": p.musteri_adi or "?",
                        "id": p.musteri_id or "",
                        "tutar": p.tutar,
                        "durum": p.durum or p.islem_tipi.value,
                        "tarih": m["date"][:16],
                        "iban": p.iban or ""
                    })

            if not yatirimlar:
                await msg.edit_text("ℹ️ Son 7 günde yatırım işlemi bulunamadı.")
                return

            bekleyen = [y for y in yatirimlar if y["durum"] in ("bekleyen", "beklemede")]
            red = [y for y in yatirimlar if y["durum"] in ("reddedildi", "red")]

            text = f"💰 **Yatırım İşlemleri** (son 7 gün)\n\n"

            if bekleyen:
                text += f"⏳ **BEKLEYEN ({len(bekleyen)}):**\n"
                for y in bekleyen[:5]:
                    text += f"  • {y['isim']} | ₺{y['tutar'] or '?'} | {y['tarih']}\n"
                text += "\n"

            if red:
                text += f"❌ **REDDEDİLEN ({len(red)}):**\n"
                for y in red[:5]:
                    text += f"  • {y['isim']} | ₺{y['tutar'] or '?'} | {y['tarih']}\n"
                text += "\n"

            text += f"📊 Toplam: {len(yatirimlar)} yatırım | {len(bekleyen)} bekleyen | {len(red)} red"

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Hata: {e}")

    async def cmd_tarih(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Belirli bir tarihteki işlemleri listele."""
        if not self._is_admin(update.effective_user.id):
            return

        if not context.args:
            await update.message.reply_text(
                "Kullanım: `/tarih <GG.AA>` veya `/tarih <GG.AA.YYYY>`\n"
                "Örnek: `/tarih 02.06` veya `/tarih 02.06.2026`",
                parse_mode="Markdown"
            )
            return

        from parser import MessageParser
        from database import get_messages_by_group
        import re

        date_str = context.args[0]
        # GG.AA formatı → 2026-AA-GG
        match = re.match(r'(\d{2})\.(\d{2})(?:\.(\d{4}))?', date_str)
        if not match:
            await update.message.reply_text("❌ Geçersiz tarih formatı. Örnek: `02.06`", parse_mode="Markdown")
            return

        day, month, year = match.group(1), match.group(2), match.group(3) or "2026"
        date_prefix = f"{year}-{month}-{day}"

        msg = await update.message.reply_text(f"🔍 {date_str} tarihli işlemler aranıyor...")

        try:
            parser = MessageParser()
            all_msgs = await get_messages_by_group("source", limit=5000)
            all_msgs += await get_messages_by_group("verify", limit=5000)

            # Tarihe göre filtrele
            day_msgs = [m for m in all_msgs if m["date"].startswith(date_prefix)]

            if not day_msgs:
                await msg.edit_text(f"ℹ️ {date_str} tarihinde mesaj bulunamadı.")
                return

            # Parse et ve anlamlı olanları göster
            parsed_items = []
            for m in day_msgs:
                p = parser.parse(m["text"])
                if p.musteri_adi or p.musteri_id or p.tutar or p.islem_hash:
                    parsed_items.append((m, p))

            text = f"📅 **{date_str} Tarihli İşlemler**\n"
            text += f"Toplam mesaj: {len(day_msgs)} | Anlamlı: {len(parsed_items)}\n\n"

            # Yapılandırılmış blokları göster
            structured = [(m, p) for m, p in parsed_items if p.is_structured]
            if structured:
                text += f"📋 **Yapılandırılmış İşlemler ({len(structured)}):**\n"
                for m, p in structured[:10]:
                    icon = "💸" if p.tutar_yonu == "cekim" else "💰"
                    status = p.durum or p.islem_tipi.value
                    text += f"  {icon} {p.musteri_adi or '?'} | ₺{p.tutar or '?'} | {status}\n"
                text += "\n"

            # İptal/red işlemleri
            issues = [(m, p) for m, p in parsed_items
                     if p.islem_tipi.value in ("cekim_iptal", "iptal", "red")]
            if issues:
                text += f"🚫 **İptal/Red ({len(issues)}):**\n"
                for m, p in issues[:5]:
                    text += f"  • {p.musteri_adi or '?'} | {p.islem_tipi.value}\n"

            if not structured and not issues:
                text += "ℹ️ Yapılandırılmış işlem veya iptal/red bulunamadı.\n"
                text += "Genel mesajlar mevcut — /search ile arayabilirsiniz."

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Hata: {e}")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        text = (
            "📖 **Ödeme Doğrulama Botu - Yardım**\n\n"
            "Bu bot, operasyon grubundaki mesajları tarayarak "
            "ödeme/API grubundaki mesajlarla çapraz doğrulama yapar.\n\n"
            "**Temel Akış:**\n"
            "1. `/scan` ile grupları tarayın\n"
            "2. `/verify` ile doğrulamayı çalıştırın\n"
            "3. `/report` ile sonuçları görün\n\n"
            "**Otomatik Kontroller:**\n"
            "• Çekim iptal edilmiş ama ödeme yapılmış\n"
            "• Personel onay vermiş ama API red döndü\n"
            "• Ödeme sağlanmış ama sistem red veriyor\n"
            "• Tutar uyuşmazlığı\n"
            "• İşlem eşleşme (ID, isim, tutar, hash)\n\n"
            "**Sorgulama:**\n"
            "`/musteri <isim/ID>` - Müşteri detayı\n"
            "`/tutarsizlik` - Tüm tutarsızlıklar\n"
            "`/search <metin>` - Serbest arama\n\n"
            "**Durum Kodları:**\n"
            "✅ Doğrulanmış | ⚠️ Kısmi | 🔴 Tutarsız | ❌ Red | ⏳ Bekleyen"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    def build(self) -> Application:
        self.app = Application.builder().token(Config.BOT_TOKEN).build()

        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("verify", self.cmd_verify))
        self.app.add_handler(CommandHandler("report", self.cmd_report))
        self.app.add_handler(CommandHandler("rules", self.cmd_rules))
        self.app.add_handler(CommandHandler("addrule", self.cmd_addrule))
        self.app.add_handler(CommandHandler("search", self.cmd_search))
        self.app.add_handler(CommandHandler("api", self.cmd_api))
        self.app.add_handler(CommandHandler("musteri", self.cmd_musteri))
        self.app.add_handler(CommandHandler("tutarsizlik", self.cmd_tutarsizlik))
        self.app.add_handler(CommandHandler("tutarsiz", self.cmd_tutarsizlik))
        self.app.add_handler(CommandHandler("cekim", self.cmd_cekim))
        self.app.add_handler(CommandHandler("yatirim", self.cmd_yatirim))
        self.app.add_handler(CommandHandler("tarih", self.cmd_tarih))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("help", self.cmd_help))

        return self.app
