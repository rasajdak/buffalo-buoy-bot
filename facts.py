"""Curated, verified Buffalo-harbor / Lake-Erie facts & history.

These are the *grounding* material for the Captain's Log: the LLM weaves one in
rather than inventing history. Keep every entry factual and checkable. Rotation
state lives in state/facts_state.json so we cycle through before repeating.
"""

from __future__ import annotations

import json
import random

import config

FACTS = [
    "Lake Erie is the shallowest of the Great Lakes — averaging only about 62 feet deep — so it warms fast in summer and is the one Great Lake that routinely freezes nearly over in winter.",
    "Because it's so shallow, Erie kicks up steep, closely-spaced waves faster than any other Great Lake. Old hands consider it the most temperamental water of the five.",
    "The eastern basin, where the Buffalo Buoy rides, is Lake Erie's deepest — over 200 feet down near Long Point on the Canadian side.",
    "Prevailing southwest winds shove Lake Erie's water toward Buffalo at the northeast end, so a hard blow can literally pile the lake up against the city — a phenomenon called a seiche.",
    "On October 18, 1844, a storm-driven seiche sent Lake Erie surging over Buffalo's seawall; the flood killed at least 78 people and helped spur the city to build stronger breakwaters.",
    "The Erie Canal opened in 1825, linking Lake Erie at Buffalo to the Hudson River and New York City — and almost overnight turned Buffalo into a booming Great Lakes port.",
    "Buffalo grew into the world's largest grain port. In 1843, merchant Joseph Dart built the first steam-powered grain elevator here, mechanizing the transfer of grain from ship to silo.",
    "Lake Erie is often called the 'Walleye Capital of the World' for the enormous walleye fishery that draws anglers from across the country.",
    "Water entering Lake Erie stays only about 2.6 years on average — the shortest retention time of any Great Lake — before flowing out the Niagara River.",
    "Everything that flows out of Lake Erie heads down the Niagara River and over Niagara Falls on its way to Lake Ontario and, eventually, the sea.",
    "Each winter since 1964, the Lake Erie Ice Boom — a floating chain of steel pontoons — is strung across the lake's outlet near Buffalo to keep drifting ice from jamming the Niagara River.",
    "Lake Erie holds only about 2 percent of all the water in the Great Lakes, despite its size — that's how shallow it is.",
    "The lake takes its name from the Erie people, an Iroquoian nation who lived along its southern shore before the seventeenth century.",
    "The Buffalo Main Light, a stone lighthouse at the harbor mouth, has stood since 1833 and is one of the oldest structures in the city.",
    "The Great Lakes Storm of 1913 — the 'White Hurricane' — struck with hurricane-force winds and remains the deadliest disaster in Great Lakes maritime history.",
    "Long Point, a 25-mile sand spit reaching out from the Canadian shore, wrecked so many vessels that the eastern basin around it earned the name 'Graveyard of Lake Erie.'",
    "In the Battle of Lake Erie on September 10, 1813, Oliver Hazard Perry defeated the British fleet and reported, 'We have met the enemy and they are ours.'",
    "Lake Erie is the eleventh-largest lake in the world by surface area, spanning nearly 10,000 square miles.",
    "The shallow western basin of Lake Erie can warm into the 70s Fahrenheit in high summer — practically bathwater by Great Lakes standards.",
    "Driven by wind, Lake Erie's winter ice can pile into towering shove ridges along the Buffalo shore, burying breakwalls and lighthouses in white.",
]


def _state_path():
    return config.STATE_DIR / "facts_state.json"


def next_fact() -> str:
    """Return a fact, cycling through all before repeating (shuffled each cycle)."""
    path = _state_path()
    order = []
    if path.exists():
        order = json.loads(path.read_text()).get("remaining", [])
    # validate against current list length; reshuffle when exhausted/invalid
    if not order or max(order) >= len(FACTS):
        order = list(range(len(FACTS)))
        random.shuffle(order)
    idx = order.pop()
    path.write_text(json.dumps({"remaining": order}))
    return FACTS[idx]


if __name__ == "__main__":
    for _ in range(3):
        print("-", next_fact())
