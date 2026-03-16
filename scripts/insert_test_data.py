"""插入测试数据脚本"""
import asyncio
import uuid
from datetime import datetime, timezone
import asyncpg
from neo4j import AsyncGraphDatabase

POSTGRES_DSN = "postgresql://postgres:postgres@localhost:5432/news_discovery"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "testpass123")


async def insert_postgres_data():
    conn = await asyncpg.connect(POSTGRES_DSN)
    
    articles = [
        {
            "id": str(uuid.uuid4()),
            "url": f"https://example.com/news/{i}",
            "title": f"测试新闻标题 {i}",
            "body": f"这是第 {i} 篇测试新闻的正文内容。" * 50,
            "source": "test_source",
            "source_host": "example.com",
            "category": ["科技", "财经", "政治", "体育", "娱乐"][i % 5],
            "is_news": True,
            "status": "pending",
            "credibility_score": 0.5 + (i % 5) * 0.1,
        }
        for i in range(1, 21)
    ]
    
    for article in articles:
        await conn.execute(
            """
            INSERT INTO articles (id, url, title, body, source, source_host, category, is_news, status, credibility_score, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (url) DO NOTHING
            """,
            article["id"],
            article["url"],
            article["title"],
            article["body"],
            article["source"],
            article["source_host"],
            article["category"],
            article["is_news"],
            article["status"],
            article["credibility_score"],
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
    
    sources = [
        {"host": "reuters.com", "name": "Reuters", "authority_score": 0.95, "tier": 1},
        {"host": "bbc.com", "name": "BBC", "authority_score": 0.92, "tier": 1},
        {"host": "cnn.com", "name": "CNN", "authority_score": 0.88, "tier": 1},
        {"host": "example.com", "name": "Example News", "authority_score": 0.60, "tier": 2},
        {"host": "blog.example.com", "name": "Example Blog", "authority_score": 0.40, "tier": 3},
    ]
    
    for source in sources:
        await conn.execute(
            """
            INSERT INTO source_authorities (host, name, authority_score, tier, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (host) DO UPDATE SET authority_score = $3, tier = $4
            """,
            source["host"],
            source["name"],
            source["authority_score"],
            source["tier"],
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
    
    await conn.close()
    print(f"✅ PostgreSQL: 插入 {len(articles)} 篇文章, {len(sources)} 个来源")


async def insert_neo4j_data():
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    await driver.verify_connectivity()
    
    async with driver.session() as session:
        entities = [
            {"name": "张三", "type": "person", "description": "测试人物"},
            {"name": "李四", "type": "person", "description": "测试人物"},
            {"name": "阿里巴巴", "type": "organization", "description": "科技公司"},
            {"name": "腾讯", "type": "organization", "description": "科技公司"},
            {"name": "北京", "type": "location", "description": "中国首都"},
            {"name": "上海", "type": "location", "description": "中国城市"},
        ]
        
        for entity in entities:
            await session.run(
                """
                MERGE (e:Entity {canonical_name: $name, type: $type})
                SET e.description = $description,
                    e.aliases = [],
                    e.created_at = datetime(),
                    e.updated_at = datetime()
                """,
                name=entity["name"],
                type=entity["type"],
                description=entity["description"],
            )
        
        relations = [
            {"from": "张三", "to": "阿里巴巴", "type": "WORKS_AT"},
            {"from": "李四", "to": "腾讯", "type": "WORKS_AT"},
            {"from": "张三", "to": "北京", "type": "LIVES_IN"},
            {"from": "李四", "to": "上海", "type": "LIVES_IN"},
        ]
        
        for rel in relations:
            await session.run(
                """
                MATCH (a:Entity {canonical_name: $from})
                MATCH (b:Entity {canonical_name: $to})
                MERGE (a)-[r:RELATES {type: $type}]->(b)
                """,
                from=rel["from"],
                to=rel["to"],
                type=rel["type"],
            )
    
    await driver.close()
    print(f"✅ Neo4j: 插入 {len(entities)} 个实体, {len(relations)} 个关系")


async def insert_redis_data():
    import redis
    r = redis.Redis(host="localhost", port=6379, db=0)
    
    test_urls = [f"https://example.com/news/{i}" for i in range(1, 11)]
    for url in test_urls:
        r.sadd("processed_urls", url)
    
    r.set("test_key", "test_value")
    
    print(f"✅ Redis: 插入 {len(test_urls)} 个已处理URL")


async def main():
    print("开始插入测试数据...")
    print()
    
    await insert_postgres_data()
    await insert_neo4j_data()
    await insert_redis_data()
    
    print()
    print("🎉 测试数据插入完成！")


if __name__ == "__main__":
    asyncio.run(main())
