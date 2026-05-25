"""Load digest channels into database."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import async_session, init_db
from app.services.digest import add_channel

CHANNELS = [
    {"id":"1","name":"По Уши в Гембле","username":"po_ushi_v_gambling","cat":"seo"},
    {"id":"2","name":"MAXGAMBLER","username":"maxxxigaming","cat":"seo"},
    {"id":"3","name":"Igor Bakalov","username":"bakalov_info","cat":"seo"},
    {"id":"4","name":"SEO Dream Team","username":"seodreamteamofficial","cat":"seo"},
    {"id":"5","name":"SEOшница","username":"bakushevaseo","cat":"seo"},
    {"id":"6","name":"Тихий час","username":"tkhychs","cat":"seo"},
    {"id":"7","name":"Phoenix Project","username":"seoetc","cat":"seo"},
    {"id":"8","name":"Netkela","username":"netkela","cat":"seo"},
    {"id":"9","name":"SЕalytics","username":"sealytics","cat":"seo"},
    {"id":"10","name":"Аффилиатка и АИшка","username":"aiseosales","cat":"seo"},
    {"id":"11","name":"Партнеркин Гемблинг","username":"partnerkin_gambling","cat":"news"},
    {"id":"12","name":"Highroller","username":"highroller_affiliate","cat":"news"},
    {"id":"13","name":"iGaming in High-Risk","username":"igaming_highrisk","cat":"news"},
    {"id":"14","name":"R2B.News","username":"r2b_news","cat":"news"},
    {"id":"15","name":"Oleg Shestakov","username":"shestakov_oleg","cat":"news"},
    {"id":"16","name":"Подслушано в гембле","username":"podslushano_gamble","cat":"news"},
    {"id":"17","name":"iGaming PUSH","username":"igaming_push","cat":"news"},
    {"id":"18","name":"iGaming Kitchen","username":"igaming_kitchen","cat":"news"},
    {"id":"19","name":"Gambla4","username":"gambla4","cat":"news"},
    {"id":"20","name":"iGamingNews","username":"igamingnews_tg","cat":"news"},
    {"id":"21","name":"iGaming Редакция","username":"igaming_redakciya","cat":"news"},
    {"id":"22","name":"R2B.Work","username":"r2b_work","cat":"news"},
    {"id":"23","name":"Три топора","username":"tri_topora","cat":"news"},
    {"id":"24","name":"Вредный бук","username":"vredniy_buk","cat":"news"},
    {"id":"25","name":"ГэмблХаус","username":"gamblehouse","cat":"news"},
    {"id":"26","name":"PMP Media","username":"pmp_media","cat":"news"},
    {"id":"27","name":"whitehat.media","username":"whitehattea","cat":"seo"},
    {"id":"28","name":"Бабло побеждает зло!","username":"MoneyBeatsEvil","cat":"seo"},
    {"id":"29","name":"iGaming CMO","username":"igaming_cmo","cat":"news"},
    {"id":"30","name":"iGaming Insides","username":"igaming_insides","cat":"news"},
    {"id":"31","name":"GGM iGaming People","username":"ggm_igaming","cat":"news"},
    {"id":"32","name":"C-lvl Лидеры iGaming","username":"clvl_igaming","cat":"news"},
    {"id":"33","name":"Новости букмекеров","username":"novosti_bk","cat":"news"},
    {"id":"34","name":"iGaming CEO","username":"igaming_ceo","cat":"news"},
    {"id":"35","name":"Спортивный маркетолог","username":"sport_marketolog","cat":"news"},
    {"id":"36","name":"Affiliate Diaries","username":"affiliate_diaries","cat":"seo"},
    {"id":"37","name":"AffMoment","username":"affmoment","cat":"news"},
    {"id":"38","name":"seomoneymaker","username":"seomoneymaker_channel","cat":"seo"},
    {"id":"39","name":"PM Talents","username":"pm_talents","cat":"news"},
    {"id":"40","name":"MOST","username":"most_igaming","cat":"news"},
]

async def main():
    await init_db()
    async with async_session() as db:
        loaded = 0
        for ch in CHANNELS:
            try:
                await add_channel(db, ch["id"], ch["name"], ch["username"], ch["cat"])
                loaded += 1
                print(f"  + {ch['name']}")
            except Exception as e:
                if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"  = {ch['name']} (уже есть)")
                    await db.rollback()
                else:
                    print(f"  ! {ch['name']}: {e}")
                    await db.rollback()
        print(f"\nГотово: {loaded}/{len(CHANNELS)} каналов")

if __name__ == "__main__":
    asyncio.run(main())
