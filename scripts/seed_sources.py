#!/usr/bin/env python
"""Initialize all data sources for the Weaver project.

Creates source configurations and optionally triggers the pipeline
to fetch and process articles from each source.

Usage:
    uv run scripts/seed_sources.py                          # create sources only
    uv run scripts/seed_sources.py --pipeline               # create + trigger pipeline
    uv run scripts/seed_sources.py --pipeline --max-items 5 # limit items per source
    uv run scripts/seed_sources.py --dry-run                # preview only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, f"{_project_root}/src")
sys.path.insert(0, _project_root)

# ponytail: sequential source creation, parallel triggers if throughput matters

NEWSNOW_IDS = [
    "36kr",
    "zhihu",
    "weibo",
    "bilibili",
    "douyin",
    "baidu",
    "toutiao",
    "hupu",
    "tieba",
    "douban",
    "thepaper",
    "ifeng",
    "nowcoder",
    "juejin",
    "sspai",
    "ithome",
    "coolapk",
    "v2ex",
    "github",
    "hackernews",
    "solidot",
    "producthunt",
    "xueqiu",
    "wallstreetcn",
    "gelonghui",
    "cls",
    "jin10",
    "fastbull",
    "zaobao",
    "sputniknewscn",
    "cankaoxiaoxi",
    "kaopu",
    "steam",
    "freebuf",
    "chongbuluo",
    "tencent",
    "qqvideo",
    "iqiyi",
]

RSS_FEEDS: dict[str, str] = {
    "solidot": "https://www.solidot.org/index.rss",
    "cnbeta": "https://plink.anyfeeder.com/cnbeta",
    "huxiu": "https://plink.anyfeeder.com/huxiu",
    "sixcolors": "https://feedpress.me/sixcolors",
    "36kr": "https://plink.anyfeeder.com/36kr",
    "aljazeera_news": "https://plink.anyfeeder.com/aljazeera/news",
    "appinn": "https://plink.anyfeeder.com/appinn",
    "arstechnica": "https://plink.anyfeeder.com/arstechnica",
    "bbc": "https://plink.anyfeeder.com/bbc",
    "bbc_business": "https://plink.anyfeeder.com/bbc/business",
    "bbc_education": "https://plink.anyfeeder.com/bbc/education",
    "bbc_entertainment": "https://plink.anyfeeder.com/bbc/entertainment_and_arts",
    "bbc_health": "https://plink.anyfeeder.com/bbc/health",
    "bbc_learningenglish": "https://plink.anyfeeder.com/bbc/learningenglish",
    "bbc_politics": "https://plink.anyfeeder.com/bbc/politics",
    "bbc_science": "https://plink.anyfeeder.com/bbc/science_and_environment",
    "bbc_technology": "https://plink.anyfeeder.com/bbc/technology",
    "bbc_uk": "https://plink.anyfeeder.com/bbc/uk",
    "bbc_world": "https://plink.anyfeeder.com/bbc/world",
    "businessinsider": "https://plink.anyfeeder.com/businessinsider",
    "chinadaily_caijing": "https://plink.anyfeeder.com/chinadaily/caijing",
    "chinadaily_china": "https://plink.anyfeeder.com/chinadaily/china",
    "chinadaily_column": "https://plink.anyfeeder.com/chinadaily/column",
    "chinadaily_dual": "https://plink.anyfeeder.com/chinadaily/dual",
    "chinadaily_world": "https://plink.anyfeeder.com/chinadaily/world",
    "dapenti_caijing": "https://plink.anyfeeder.com/dapenti/caijing",
    "dapenti_xilei": "https://plink.anyfeeder.com/dapenti/xilei",
    "douban_review_book": "https://plink.anyfeeder.com/douban/review/book",
    "fortunechina": "https://plink.anyfeeder.com/fortunechina",
    "fortunechina_keji": "https://plink.anyfeeder.com/fortunechina/keji",
    "fortunechina_shangye": "https://plink.anyfeeder.com/fortunechina/shangye",
    "freebuf": "https://plink.anyfeeder.com/freebuf",
    "gcores": "https://plink.anyfeeder.com/gcores",
    "guokr_scientific": "https://plink.anyfeeder.com/guokr/scientific",
    "idaily_today": "https://plink.anyfeeder.com/idaily/today",
    "ifanr": "https://plink.anyfeeder.com/ifanr",
    "infoq_recommend": "https://plink.anyfeeder.com/infoq/recommend",
    "infzm_news": "https://plink.anyfeeder.com/infzm/news",
    "infzm_recommends": "https://plink.anyfeeder.com/infzm/recommends",
    "ithome_it": "https://plink.anyfeeder.com/ithome/it",
    "jianshu_home": "https://plink.anyfeeder.com/jianshu/home",
    "jiemian_business": "https://plink.anyfeeder.com/jiemian/business",
    "jiemian_finance": "https://plink.anyfeeder.com/jiemian/finance",
    "jiemian_news": "https://plink.anyfeeder.com/jiemian/news",
    "jingjiribao": "https://plink.anyfeeder.com/jingjiribao",
    "leiphone": "https://plink.anyfeeder.com/leiphone",
    "longreads": "https://plink.anyfeeder.com/longreads",
    "mittrchina_hot": "https://plink.anyfeeder.com/mittrchina/hot",
    "mydrivers": "https://plink.anyfeeder.com/mydrivers",
    "newscn_whxw": "https://plink.anyfeeder.com/newscn/whxw",
    "nytimes_cn": "https://plink.anyfeeder.com/nytimes/cn",
    "nytimes_dual": "https://plink.anyfeeder.com/nytimes/dual",
    "pentitugua": "https://plink.anyfeeder.com/pentitugua",
    "people": "https://plink.anyfeeder.com/people",
    "people_daily": "https://plink.anyfeeder.com/people-daily",
    "people_politics": "https://plink.anyfeeder.com/people/politics",
    "people_world": "https://plink.anyfeeder.com/people/world",
    "qstheory": "https://plink.anyfeeder.com/qstheory",
    "rfi_cn": "https://plink.anyfeeder.com/rfi/cn",
    "sina_csj": "https://plink.anyfeeder.com/sina/csj",
    "ssapi_matrix": "https://plink.anyfeeder.com/ssapi/matrix",
    "sspai": "https://plink.anyfeeder.com/sspai",
    "techcrunch": "https://plink.anyfeeder.com/techcrunch",
    "time": "https://plink.anyfeeder.com/time",
    "tmtpost": "https://plink.anyfeeder.com/tmtpost",
    "toodaylab": "https://plink.anyfeeder.com/toodaylab",
    "vice": "https://plink.anyfeeder.com/vice",
    "weibo_search_hot": "https://plink.anyfeeder.com/weibo/search/hot",
    "weixin_AI_era": "https://plink.anyfeeder.com/weixin/AI_era",
    "weixin_CBNweekly": "https://plink.anyfeeder.com/weixin/CBNweekly2008",
    "weixin_DJ00123987": "https://plink.anyfeeder.com/weixin/DJ00123987",
    "weixin_DingXiangMaMi": "https://plink.anyfeeder.com/weixin/DingXiangMaMi",
    "weixin_DingXiangYiSheng": "https://plink.anyfeeder.com/weixin/DingXiangYiSheng",
    "weixin_Economist": "https://plink.anyfeeder.com/weixin/Economist_fans",
    "weixin_Guokr42": "https://plink.anyfeeder.com/weixin/Guokr42",
    "weixin_IrisMagazine": "https://plink.anyfeeder.com/weixin/IrisMagazine",
    "weixin_MSRAsia": "https://plink.anyfeeder.com/weixin/MSRAsia",
    "weixin_Notesman": "https://plink.anyfeeder.com/weixin/Notesman",
    "weixin_ScientificAmerican": "https://plink.anyfeeder.com/weixin/ScientificAmerican",
    "weixin_TheIntellectual": "https://plink.anyfeeder.com/weixin/The-Intellectual",
    "weixin_almosthuman": "https://plink.anyfeeder.com/weixin/almosthuman2014",
    "weixin_banyuetan": "https://plink.anyfeeder.com/weixin/banyuetan-weixin",
    "weixin_banzhuan": "https://plink.anyfeeder.com/weixin/banzhuanxiaozu",
    "weixin_bitsea": "https://plink.anyfeeder.com/weixin/bitsea",
    "weixin_caixinwang": "https://plink.anyfeeder.com/weixin/caixinwang",
    "weixin_caozsay": "https://plink.anyfeeder.com/weixin/caozsay",
    "weixin_capitalnews": "https://plink.anyfeeder.com/weixin/capitalnews",
    "weixin_cctvnewscenter": "https://plink.anyfeeder.com/weixin/cctvnewscenter",
    "weixin_cctvyscj": "https://plink.anyfeeder.com/weixin/cctvyscj",
    "weixin_ckxxwx": "https://plink.anyfeeder.com/weixin/ckxxwx",
    "weixin_dandureading": "https://plink.anyfeeder.com/weixin/dandureading",
    "weixin_delinshe": "https://plink.anyfeeder.com/weixin/delinshe",
    "weixin_dgjdds": "https://plink.anyfeeder.com/weixin/dgjdds",
    "weixin_dili360": "https://plink.anyfeeder.com/weixin/dili360",
    "weixin_diqiuzhishiju": "https://plink.anyfeeder.com/weixin/diqiuzhishiju",
    "weixin_doctorx666": "https://plink.anyfeeder.com/weixin/doctorx666",
    "weixin_duhaoshu": "https://plink.anyfeeder.com/weixin/duhaoshu",
    "weixin_dujinyong6": "https://plink.anyfeeder.com/weixin/dujinyong6",
    "weixin_eeo": "https://plink.anyfeeder.com/weixin/eeo-com-cn",
    "weixin_forbes": "https://plink.anyfeeder.com/weixin/forbes_china",
    "weixin_gh_10a6b96351a9": "https://plink.anyfeeder.com/weixin/gh_10a6b96351a9",
    "weixin_gjrwls": "https://plink.anyfeeder.com/weixin/gjrwls",
    "weixin_guokrpac": "https://plink.anyfeeder.com/weixin/guokrpac",
    "weixin_hbrchinese": "https://plink.anyfeeder.com/weixin/hbrchinese",
    "weixin_hqsbwx": "https://plink.anyfeeder.com/weixin/hqsbwx",
    "weixin_huxiu": "https://plink.anyfeeder.com/weixin/huxiu_com",
    "weixin_ibookreview": "https://plink.anyfeeder.com/weixin/ibookreview",
    "weixin_iceo": "https://plink.anyfeeder.com/weixin/iceo-com-cn",
    "weixin_ikanlixiang": "https://plink.anyfeeder.com/weixin/ikanlixiang",
    "weixin_ilianyue": "https://plink.anyfeeder.com/weixin/ilianyue",
    "weixin_importnew": "https://plink.anyfeeder.com/weixin/importnew",
    "weixin_jianshuio": "https://plink.anyfeeder.com/weixin/jianshuio",
    "weixin_jingjixue": "https://plink.anyfeeder.com/weixin/jingjixue_yuanli",
    "weixin_jjbd21": "https://plink.anyfeeder.com/weixin/jjbd21",
    "weixin_kejimx": "https://plink.anyfeeder.com/weixin/kejimx",
    "weixin_knowyourself": "https://plink.anyfeeder.com/weixin/knowyourself2015",
    "weixin_lengjing": "https://plink.anyfeeder.com/weixin/lengjing_qqfinance",
    "weixin_lifeweek": "https://plink.anyfeeder.com/weixin/lifeweek",
    "weixin_liweitan": "https://plink.anyfeeder.com/weixin/liweitan2014",
    "weixin_luojisw": "https://plink.anyfeeder.com/weixin/luojisw",
    "weixin_mao_talk": "https://plink.anyfeeder.com/weixin/mao-talk",
    "weixin_meigushe": "https://plink.anyfeeder.com/weixin/meigushe",
    "weixin_nanfangzhoumo": "https://plink.anyfeeder.com/weixin/nanfangzhoumo",
    "weixin_nbweekly": "https://plink.anyfeeder.com/weixin/nbweekly",
    "weixin_ndgs233": "https://plink.anyfeeder.com/weixin/ndgs233",
    "weixin_newfortune": "https://plink.anyfeeder.com/weixin/newfortune",
    "weixin_newsxinhua": "https://plink.anyfeeder.com/weixin/newsxinhua",
    "weixin_people_rmw": "https://plink.anyfeeder.com/weixin/people_rmw",
    "weixin_phoenixweekly": "https://plink.anyfeeder.com/weixin/phoenixweekly",
    "weixin_qnwzwx": "https://plink.anyfeeder.com/weixin/qnwzwx",
    "weixin_qqtech": "https://plink.anyfeeder.com/weixin/qqtech",
    "weixin_renwumag": "https://plink.anyfeeder.com/weixin/renwumag1980",
    "weixin_rmrbwx": "https://plink.anyfeeder.com/weixin/rmrbwx",
    "weixin_runliu": "https://plink.anyfeeder.com/weixin/runliu-pub",
    "weixin_sagacity": "https://plink.anyfeeder.com/weixin/sagacity-mac",
    "weixin_sanjieke01": "https://plink.anyfeeder.com/weixin/sanjieke01",
    "weixin_shudanlaile": "https://plink.anyfeeder.com/weixin/shudanlaile",
    "weixin_sports_sina": "https://plink.anyfeeder.com/weixin/sports_sina",
    "weixin_tancaijing": "https://plink.anyfeeder.com/weixin/tancaijing",
    "weixin_techread": "https://plink.anyfeeder.com/weixin/techread",
    "weixin_theeconomist": "https://plink.anyfeeder.com/weixin/theeconomist",
    "weixin_thefair2": "https://plink.anyfeeder.com/weixin/thefair2",
    "weixin_thepapernews": "https://plink.anyfeeder.com/weixin/thepapernews",
    "weixin_vistaweek": "https://plink.anyfeeder.com/weixin/vistaweek",
    "weixin_wallstreetcn": "https://plink.anyfeeder.com/weixin/wallstreetcn",
    "weixin_woshipm": "https://plink.anyfeeder.com/weixin/woshipm",
    "weixin_wowjiemian": "https://plink.anyfeeder.com/weixin/wowjiemian",
    "weixin_wuxiaobopd": "https://plink.anyfeeder.com/weixin/wuxiaobopd",
    "weixin_xiake_island": "https://plink.anyfeeder.com/weixin/xiake_island",
    "weixin_xueqiujinghua": "https://plink.anyfeeder.com/weixin/xueqiujinghua",
    "weixin_yeeyancom": "https://plink.anyfeeder.com/weixin/yeeyancom",
    "weixin_yixuejiezazhi": "https://plink.anyfeeder.com/weixin/yixuejiezazhi",
    "weixin_youshucc": "https://plink.anyfeeder.com/weixin/youshucc",
    "weixin_zhangjiawei": "https://plink.anyfeeder.com/weixin/zhangjiawei_1983",
    "woshipm_popular": "https://plink.anyfeeder.com/woshipm/popular",
    "zerohedge": "https://plink.anyfeeder.com/zerohedge",
    "zhihu_daily": "https://plink.anyfeeder.com/zhihu/daily",
}


def build_newsnow_config(source_id: str) -> dict:
    return {
        "id": f"newsnow-{source_id}",
        "name": f"NewsNow {source_id}",
        "url": f"https://newsnow.czl.net/api/s?id={source_id}",
        "source_type": "newsnow",
        "enabled": True,
        "interval_minutes": 30,
        "credibility": 0.70,
        "tier": 2,
    }


def build_rss_config(sid: str, url: str) -> dict:
    name = sid.replace("_", " ").replace("-", " ").title()
    return {
        "id": f"rss-{sid}",
        "name": name,
        "url": url,
        "source_type": "rss",
        "enabled": True,
        "interval_minutes": 30,
        "credibility": 0.70,
        "tier": 2,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Weaver data sources")
    parser.add_argument(
        "--pipeline", action="store_true", help="Trigger pipeline after creating sources"
    )
    parser.add_argument(
        "--max-items", type=int, default=None, help="Max items per source when triggering pipeline"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument(
        "--batch", type=int, default=10, help="Sources to add per batch (default: 10)"
    )
    args = parser.parse_args()

    from config.settings import Settings
    from container import Container

    settings = Settings()
    container = Container().configure(settings)
    await container.startup()

    try:
        from modules.ingestion.domain.models import SourceConfig as SourceConfigModel

        repo = container.source_config_repo()
        scheduler = container.source_scheduler()

        all_configs: list[SourceConfigModel] = []
        for sid in NEWSNOW_IDS:
            cfg = build_newsnow_config(sid)
            all_configs.append(SourceConfigModel(**cfg))
        for sid, url in RSS_FEEDS.items():
            cfg = build_rss_config(sid, url)
            all_configs.append(SourceConfigModel(**cfg))

        print(f"Total sources to create: {len(all_configs)}")
        print(f"  NewsNow: {len(NEWSNOW_IDS)}")
        print(f"  RSS:     {len(RSS_FEEDS)}")

        if args.dry_run:
            print("\nDry-run: no changes made")
            return 0

        added = 0
        skipped = 0
        batches = [all_configs[i : i + args.batch] for i in range(0, len(all_configs), args.batch)]

        for batch_num, batch in enumerate(batches, 1):
            print(f"\nBatch {batch_num}/{len(batches)} ({len(batch)} sources)...")
            for cfg in batch:
                try:
                    await repo.upsert(cfg)
                    added += 1
                except Exception as e:
                    skipped += 1

            await asyncio.sleep(0.5)

        print(f"\nDone: {added} created, {skipped} skipped")

        if args.pipeline:
            print("\nTriggering pipeline...")
            triggered = 0
            failed = 0
            for sc in all_configs:
                try:
                    await scheduler.trigger_now(sc.id, max_items=args.max_items)
                    triggered += 1
                    print(f"  ✓ {sc.id}")
                except Exception as e:
                    failed += 1
                    print(f"  ✗ {sc.id}: {e}")
            print(f"Pipeline triggered: {triggered} succeeded, {failed} failed")

        return 0

    finally:
        await container.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
