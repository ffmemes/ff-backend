"""Synthetic-only benchmark; requires an empty disposable PostgreSQL on localhost:55441.

This deliberately has no production configuration or connection option. Run
only in a task-owned tmpfs PostgreSQL container, and remove it after the run.
"""

import ast
import asyncio
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PARAMETERS = ("pool", "user_id", "recommended_by", "excluded", "ru_chat_id", "en_chat_id", "limit")
DDL = """
CREATE TABLE meme(id integer PRIMARY KEY, type text NOT NULL, telegram_file_id text,
 caption text, language_code text, meme_source_id integer, status text NOT NULL,
 duplicate_of integer);
CREATE INDEX meme_status_idx ON meme(status);
CREATE INDEX meme_language_code_idx ON meme(language_code);
CREATE INDEX meme_type_idx ON meme(type);
CREATE INDEX meme_source_idx ON meme(meme_source_id);
CREATE INDEX ix_meme_duplicate_of ON meme(duplicate_of);
CREATE TABLE meme_stats(meme_id integer PRIMARY KEY, nlikes integer);
CREATE TABLE user_language(user_id bigint, language_code text,
 PRIMARY KEY(user_id,language_code));
CREATE TABLE user_meme_source_stats(user_id bigint,meme_source_id integer,
 nlikes integer,ndislikes integer,PRIMARY KEY(user_id,meme_source_id));
CREATE TABLE user_meme_reaction(user_id bigint,meme_id integer,
 PRIMARY KEY(user_id,meme_id));
CREATE INDEX reaction_meme_user ON user_meme_reaction(meme_id,user_id);
CREATE TABLE crossposting(channel text,meme_id integer,PRIMARY KEY(channel,meme_id));
CREATE TABLE user_channel_membership(user_id bigint,chat_id bigint,status text,
 ever_member boolean,observed_at timestamp,PRIMARY KEY(user_id,chat_id));
CREATE TABLE user_tg_chat_membership(user_tg_id bigint,chat_id bigint,
 PRIMARY KEY(user_tg_id,chat_id));
INSERT INTO meme SELECT g,'image','synthetic-file-'||g,repeat('synthetic caption ',5),
 CASE WHEN g%2=0 THEN 'ru' ELSE 'en' END,1+g%1000,
 CASE WHEN g>225000 THEN 'duplicate' WHEN g<=10000 THEN 'published' ELSE 'ok' END,
 CASE WHEN g>249900 THEN 225001+(g-249901)%400
      WHEN g>225000 THEN 1+(g-225001)*9 ELSE NULL END
 FROM generate_series(1,250000) g;
INSERT INTO meme_stats SELECT g,20+g%100 FROM generate_series(1,250000) g;
INSERT INTO user_language VALUES(1,'ru'),(1,'en');
INSERT INTO user_meme_source_stats SELECT 1,g,20,10 FROM generate_series(1,1000) g;
INSERT INTO user_meme_reaction SELECT 2+(g/100),1+g%250000
 FROM generate_series(1,400000) g;
INSERT INTO user_meme_reaction SELECT 1,1+(g*97)%250000 FROM generate_series(1,2000) g;
INSERT INTO crossposting SELECT CASE WHEN g%2=0 THEN 'tgchannelru' ELSE 'tgchannelen' END,g
 FROM generate_series(1,10000) g;
INSERT INTO crossposting SELECT 'tgchannelen',g FROM generate_series(225001,225100) g;
INSERT INTO user_channel_membership VALUES
 (1,-101,'nonmember',false,timezone('UTC',now())),
 (1,-102,'nonmember',false,timezone('UTC',now()));
ANALYZE;
"""


def parameterize(query):
    import re

    for index, name in enumerate(PARAMETERS, 1):
        query = re.sub(r":" + name + r"\b", "$" + str(index), query)
    return query


def slow_nodes(plan):
    nodes = []

    def walk(node):
        nodes.append(
            {
                key: node[key]
                for key in (
                    "Node Type",
                    "Relation Name",
                    "Subplan Name",
                    "Index Name",
                    "Actual Rows",
                    "Actual Loops",
                    "Actual Total Time",
                    "Rows Removed by Filter",
                    "Rows Removed by Join Filter",
                )
                if key in node
            }
        )
        for child in node.get("Plans", []):
            walk(child)

    walk(plan)
    return sorted(
        nodes,
        key=lambda node: node.get("Actual Total Time", 0) * node.get("Actual Loops", 1),
        reverse=True,
    )[:25]


async def main():
    tree = ast.parse((ROOT / "src/recommendations/channel_hits.py").read_text())
    original = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "ELIGIBLE_SQL" for target in node.targets
        )
    )
    optimized = (HERE / "eligibility-query-optimized.sql").read_text()
    queries = {"original": parameterize(original), "optimized": parameterize(optimized)}
    conn = await asyncpg.connect(
        host="127.0.0.1", port=55441, user="postgres",
        password="postgres", database="postgres",
        server_settings={"statement_timeout": "120000", "timezone": "UTC"},
    )
    try:
        await conn.execute(DDL)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        pool = [
            {"id": n, "percentile": n / 400, "posted_at": now.isoformat()} for n in range(1, 401)
        ]
        args = [json.dumps(pool), 1, "channel_hit_v1", [], -101, -102, 1]
        result = {
            "as_of_utc": now.isoformat(),
            "postgres": await conn.fetchval("SELECT version()"),
            "database_bytes": await conn.fetchval("SELECT pg_database_size(current_database())"),
            "synthetic_counts": {
                "memes": 250000,
                "aliases": 25000,
                "reactions": 402000,
                "crossposts": 10100,
                "pool": 400,
            },
            "query_hashes": {
                name: hashlib.sha256(query.encode()).hexdigest() for name, query in queries.items()
            },
            "runs": {},
            "equivalence_checks": [],
        }
        for name, query in queries.items():
            for size in (400, 1):
                args[0] = json.dumps(pool if size == 400 else [pool[-1]])
                samples = []
                last = None
                for _ in range(4):
                    last = json.loads(
                        await conn.fetchval(
                            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query,
                            *args,
                        )
                    )[0]
                    samples.append(last["Execution Time"])
                result["runs"][f"{name}_pool{size}"] = {
                    "execution_ms": samples,
                    "warm_median_ms": statistics.median(samples[1:]),
                    "planning_ms": last["Planning Time"],
                    "nodes": slow_nodes(last["Plan"]),
                    "jit": last.get("JIT"),
                }

        args[0], args[-1] = json.dumps(pool), 400

        async def compare(label, mutation=None, forbidden=()):
            transaction = conn.transaction()
            await transaction.start()
            try:
                if mutation:
                    await conn.execute(mutation)
                before = [dict(row) for row in await conn.fetch(queries["original"], *args)]
                after = [dict(row) for row in await conn.fetch(queries["optimized"], *args)]
                assert before == after, label + ": query results differ"
                assert not set(forbidden) & {row["id"] for row in after}, label
                result["equivalence_checks"].append({"case": label, "matched_rows": len(after)})
            finally:
                await transaction.rollback()

        await compare("baseline")
        await compare(
            "current_channel_member",
            "UPDATE user_channel_membership SET status='member' WHERE chat_id=-102",
            [1, 10],
        )
        await compare(
            "unknown_including_alias_publication",
            "UPDATE user_channel_membership SET status='unknown' WHERE chat_id=-102",
            [1, 10],
        )
        await compare(
            "missing_membership", "DELETE FROM user_channel_membership WHERE chat_id=-101", [2, 400]
        )
        await compare(
            "expired_membership",
            "UPDATE user_channel_membership SET "
            "observed_at=timezone('UTC',now())-interval '25 hours' WHERE chat_id=-101",
            [2, 400],
        )
        await compare(
            "historical_positive", "INSERT INTO user_tg_chat_membership VALUES(1,-101)", [2, 400]
        )
        await compare(
            "sticky_ever_member",
            "UPDATE user_channel_membership SET ever_member=true WHERE chat_id=-102",
            [1, 10],
        )
        await compare(
            "direct_alias_seen",
            "INSERT INTO user_meme_reaction VALUES(1,225001) ON CONFLICT DO NOTHING",
            [1],
        )
        await compare(
            "two_hop_alias_seen",
            "INSERT INTO user_meme_reaction VALUES(1,249901) ON CONFLICT DO NOTHING",
            [1],
        )
        await compare("status_changed", "UPDATE meme SET status='ok' WHERE id=400", [400])
        await compare("canonical_changed", "UPDATE meme SET duplicate_of=399 WHERE id=400", [400])
        args[3] = [399, 400]
        await compare("explicit_exclusions", forbidden=[399, 400])
        args[3] = []
        args[0] = json.dumps(pool + [dict(pool[-1], percentile=0.01)])
        await compare("duplicate_pool_id")

        (HERE / "synthetic-eligibility-optimized-benchmark.json").write_text(
            json.dumps(result, indent=2) + "\n",
        )
        print(
            json.dumps(
                {
                    "runs": {
                        key: {
                            "warm_median_ms": value["warm_median_ms"],
                            "execution_ms": value["execution_ms"],
                        }
                        for key, value in result["runs"].items()
                    },
                    "equivalence_checks": result["equivalence_checks"],
                    "database_bytes": result["database_bytes"],
                },
                indent=2,
            )
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
