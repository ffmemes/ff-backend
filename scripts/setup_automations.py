"""Create Prefect automations for ff-backend.

Run AFTER serve_flows.py has registered deployments:
    python scripts/setup_automations.py

Idempotent — deletes and recreates all ff:* automations.
"""

import asyncio
import sys
from datetime import timedelta

from prefect.automations import Automation, EventTrigger, Posture
from prefect.client import get_client
from prefect.events.actions import PauseDeployment, RunDeployment

# Full deployment names: "flow_name/deployment_name"
DEPLOYMENT_NAMES = {
    "parse_tg": "Parse Telegram Channels/Parse Telegram Sources",
    "parse_vk": "Parse VK Groups/Parse VK Sources",
    "parse_ig": "Parse Instagram Groups/Parse Instagram Sources",
    "tg_pipeline": "Memes from Telegram Pipeline/TG Meme Pipeline",
    "vk_pipeline": "Memes from VK Pipeline/VK Meme Pipeline",
    "ig_pipeline": "Memes from Instagram Pipeline/IG Meme Pipeline",
    "final_pipeline": "Final Memes Pipeline/Final Meme Pipeline",
    "stats_meme": "Calculate meme_stats/Calculate meme_stats",
    "stats_user": "Calculate user_stats/Calculate user_stats",
    "stats_source": "Calculate meme_source_stats/Calculate meme_source_stats",
    "stats_ums": "Calculate user_meme_source_stats/Calculate user_meme_source_stats",
    "describe": "Describe Memes (OpenRouter Vision)/Describe Memes (OpenRouter)",
}

PREFIX = "ff:"


async def resolve_deployment_ids() -> dict[str, str]:
    """Look up deployment UUIDs by name."""
    ids = {}
    async with get_client() as client:
        for key, name in DEPLOYMENT_NAMES.items():
            try:
                dep = await client.read_deployment_by_name(name)
                ids[key] = dep.id
                print(f"  + {key}: {dep.id}")
            except Exception as e:
                print(f"  - {key} ({name}): {e}")
    return ids


async def delete_existing_automations():
    """Delete all automations with our prefix."""
    async with get_client() as client:
        automations = await client.read_automations()
        count = 0
        for auto in automations:
            if auto.name.startswith(PREFIX):
                await client.delete_automation(auto.id)
                print(f"  Deleted: {auto.name}")
                count += 1
        if count == 0:
            print("  (none found)")


def _deployment_trigger(
    deployment_id, event: str, posture=Posture.Reactive, threshold=1, within_minutes=0
) -> EventTrigger:
    return EventTrigger(
        posture=posture,
        expect={event},
        match_related={
            "prefect.resource.id": f"prefect.deployment.{deployment_id}",
            "prefect.resource.role": "deployment",
        },
        threshold=threshold,
        within=timedelta(minutes=within_minutes),
    )


async def create_automations(ids: dict):
    """Create all automations."""
    created = []

    # ── Flow chaining: parser -> pipeline ──
    chains = [
        ("parse_tg", "tg_pipeline", "TG parser -> TG pipeline"),
        ("parse_vk", "vk_pipeline", "VK parser -> VK pipeline"),
        ("parse_ig", "ig_pipeline", "IG parser -> IG pipeline"),
    ]
    for source, target, desc in chains:
        if source in ids and target in ids:
            auto = Automation(
                name=f"{PREFIX}chain:{source}->{target}",
                description=desc,
                trigger=_deployment_trigger(ids[source], "prefect.flow-run.Completed"),
                actions=[RunDeployment(deployment_id=ids[target])],
            )
            await auto.acreate()
            created.append(auto.name)

    # ── Flow chaining: pipeline -> final_pipeline ──
    for pipeline_key in ("tg_pipeline", "vk_pipeline", "ig_pipeline"):
        if pipeline_key in ids and "final_pipeline" in ids:
            auto = Automation(
                name=f"{PREFIX}chain:{pipeline_key}->final",
                description=f"{pipeline_key} -> final pipeline",
                trigger=_deployment_trigger(ids[pipeline_key], "prefect.flow-run.Completed"),
                actions=[RunDeployment(deployment_id=ids["final_pipeline"])],
            )
            await auto.acreate()
            created.append(auto.name)

    # ── Proactive monitors (replace watchdog) ──
    # If a flow hasn't completed within its expected window, re-trigger it.
    monitors = [
        ("stats_meme", 75, "meme_stats not completed in 75 min"),
        ("stats_user", 75, "user_stats not completed in 75 min"),
        ("parse_tg", 120, "TG parser not completed in 2 hours"),
    ]
    for dep_key, minutes, desc in monitors:
        if dep_key in ids:
            auto = Automation(
                name=f"{PREFIX}monitor:{dep_key}",
                description=f"Auto-retrigger: {desc}",
                trigger=_deployment_trigger(
                    ids[dep_key],
                    "prefect.flow-run.Completed",
                    posture=Posture.Proactive,
                    within_minutes=minutes,
                ),
                actions=[RunDeployment(deployment_id=ids[dep_key])],
            )
            await auto.acreate()
            created.append(auto.name)

    # ── Safety net: final pipeline not completed in 3h ──
    if "final_pipeline" in ids:
        auto = Automation(
            name=f"{PREFIX}monitor:final_pipeline",
            description="Safety net: final pipeline not completed in 3 hours",
            trigger=_deployment_trigger(
                ids["final_pipeline"],
                "prefect.flow-run.Completed",
                posture=Posture.Proactive,
                within_minutes=180,
            ),
            actions=[RunDeployment(deployment_id=ids["final_pipeline"])],
        )
        await auto.acreate()
        created.append(auto.name)

    # ── Circuit breakers: pause deployment after repeated failures ──
    circuits = [
        ("parse_tg", 3, 30, "Pause TG parser after 3 failures in 30 min"),
        ("parse_vk", 3, 30, "Pause VK parser after 3 failures in 30 min"),
        ("describe", 3, 60, "Pause describe_memes after 3 failures in 1h"),
    ]
    for dep_key, failures, minutes, desc in circuits:
        if dep_key in ids:
            auto = Automation(
                name=f"{PREFIX}circuit:{dep_key}",
                description=desc,
                trigger=_deployment_trigger(
                    ids[dep_key],
                    "prefect.flow-run.Failed",
                    threshold=failures,
                    within_minutes=minutes,
                ),
                actions=[PauseDeployment(deployment_id=ids[dep_key])],
            )
            await auto.acreate()
            created.append(auto.name)

    for name in created:
        print(f"  Created: {name}")

    print(f"\nTotal: {len(created)} automations created.")


async def main():
    print("Step 1: Deleting existing ff:* automations...")
    await delete_existing_automations()

    print("\nStep 2: Resolving deployment IDs...")
    ids = await resolve_deployment_ids()

    if not ids:
        print("\nERROR: No deployments found. Start serve_flows.py first.")
        sys.exit(1)

    print(f"\nStep 3: Creating automations ({len(ids)} deployments found)...")
    await create_automations(ids)

    print("\nDone! Automations are active.")


if __name__ == "__main__":
    asyncio.run(main())
