from __future__ import annotations

import re
from typing import Any


ALIASES = {
    "木头": "oak_log",
    "原木": "oak_log",
    "橡木": "oak_log",
    "橡木原木": "oak_log",
    "木板": "oak_planks",
    "橡木木板": "oak_planks",
    "工作台": "crafting_table",
    "木棍": "stick",
    "棍子": "stick",
    "火把": "torch",
    "箱子": "chest",
    "熔炉": "furnace",
    "石镐": "stone_pickaxe",
    "铁镐": "iron_pickaxe",
    "钻石镐": "diamond_pickaxe",
    "桶": "bucket",
    "水桶": "water_bucket",
    "指南针": "compass",
    "纸": "paper",
    "书": "book",
    "床": "white_bed",
    "白床": "white_bed",
    "面包": "bread",
    "盾牌": "shield",
    "钻石": "diamond",
    "钻石矿": "diamond_ore",
    "钻石矿石": "diamond_ore",
    "远古残骸": "ancient_debris",
    "下界合金碎片": "netherite_scrap",
    "下界合金锭": "netherite_ingot",
}


ITEMS: dict[str, dict[str, Any]] = {
    "minecraft:oak_log": {
        "name": "Oak Log",
        "kind": "block",
        "stack_size": 64,
        "obtained_from": ["Oak trees"],
        "uses": ["Craft planks", "Fuel", "Building"],
        "notes": ["Any log can usually substitute where a recipe uses the #minecraft:logs tag."],
    },
    "minecraft:oak_planks": {
        "name": "Oak Planks",
        "kind": "block",
        "stack_size": 64,
        "obtained_from": ["Crafted from oak logs"],
        "uses": ["Crafting table", "sticks", "chests", "tools", "building"],
    },
    "minecraft:stick": {
        "name": "Stick",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Crafted from planks or bamboo", "Leaf drops"],
        "uses": ["Tools", "torches", "arrows", "signs", "ladders"],
    },
    "minecraft:crafting_table": {
        "name": "Crafting Table",
        "kind": "block",
        "stack_size": 64,
        "obtained_from": ["Crafted from planks"],
        "uses": ["Unlocks 3x3 crafting recipes"],
    },
    "minecraft:furnace": {
        "name": "Furnace",
        "kind": "block",
        "stack_size": 64,
        "obtained_from": ["Crafted from cobblestone, blackstone, or cobbled deepslate"],
        "uses": ["Smelting and cooking"],
    },
    "minecraft:chest": {
        "name": "Chest",
        "kind": "block",
        "stack_size": 64,
        "obtained_from": ["Crafted from planks"],
        "uses": ["Storage", "Hoppers", "Boats with chests"],
    },
    "minecraft:torch": {
        "name": "Torch",
        "kind": "block",
        "stack_size": 64,
        "obtained_from": ["Crafted from coal or charcoal and a stick"],
        "uses": ["Lighting", "Preventing hostile mob spawning in dark areas"],
    },
    "minecraft:stone_pickaxe": {
        "name": "Stone Pickaxe",
        "kind": "tool",
        "stack_size": 1,
        "obtained_from": ["Crafted from stone-tier blocks and sticks"],
        "uses": ["Mining stone, ores up to iron-tier requirements"],
    },
    "minecraft:iron_pickaxe": {
        "name": "Iron Pickaxe",
        "kind": "tool",
        "stack_size": 1,
        "obtained_from": ["Crafted from iron ingots and sticks"],
        "uses": ["Mining diamond ore, redstone ore, gold ore, and most stone blocks"],
    },
    "minecraft:diamond_pickaxe": {
        "name": "Diamond Pickaxe",
        "kind": "tool",
        "stack_size": 1,
        "obtained_from": ["Crafted from diamonds and sticks"],
        "uses": ["Mining obsidian and ancient debris", "Netherite upgrade base"],
    },
    "minecraft:bucket": {
        "name": "Bucket",
        "kind": "item",
        "stack_size": 16,
        "obtained_from": ["Crafted from iron ingots"],
        "uses": ["Carry water, lava, milk, powder snow, fish, and axolotls"],
    },
    "minecraft:water_bucket": {
        "name": "Water Bucket",
        "kind": "item",
        "stack_size": 1,
        "obtained_from": ["Use a bucket on a water source"],
        "uses": ["Water placement", "Farms", "Fall damage prevention"],
    },
    "minecraft:compass": {
        "name": "Compass",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Crafted from iron ingots and redstone dust"],
        "uses": ["Points to world spawn unless bound to a lodestone"],
    },
    "minecraft:paper": {
        "name": "Paper",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Crafted from sugar cane"],
        "uses": ["Maps", "books", "firework rockets"],
    },
    "minecraft:book": {
        "name": "Book",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Crafted from paper and leather"],
        "uses": ["Bookshelves", "enchanting table", "written books"],
    },
    "minecraft:white_bed": {
        "name": "White Bed",
        "kind": "block",
        "stack_size": 1,
        "obtained_from": ["Crafted from wool and planks"],
        "uses": ["Sleeping", "Setting respawn point in safe dimensions"],
        "notes": ["Beds explode in the Nether and the End."],
    },
    "minecraft:bread": {
        "name": "Bread",
        "kind": "food",
        "stack_size": 64,
        "obtained_from": ["Crafted from wheat", "Village chests"],
        "uses": ["Restores 5 hunger points"],
    },
    "minecraft:shield": {
        "name": "Shield",
        "kind": "tool",
        "stack_size": 1,
        "obtained_from": ["Crafted from planks and an iron ingot"],
        "uses": ["Blocks many frontal attacks while raised"],
    },
    "minecraft:diamond": {
        "name": "Diamond",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Diamond ore", "Loot chests"],
        "uses": ["Diamond tools and armor", "Enchanting table", "Jukebox"],
    },
    "minecraft:diamond_ore": {
        "name": "Diamond Ore",
        "kind": "ore",
        "stack_size": 64,
        "obtained_from": ["Generated in the Overworld, mined with iron pickaxe or better"],
        "uses": ["Drops diamonds unless mined with Silk Touch"],
        "notes": ["Generation details are version-sensitive; use minecraft_wiki_search for exact modern distribution."],
    },
    "minecraft:ancient_debris": {
        "name": "Ancient Debris",
        "kind": "ore",
        "stack_size": 64,
        "obtained_from": ["Generated in the Nether, mined with diamond pickaxe or better"],
        "uses": ["Smelt into netherite scrap"],
    },
    "minecraft:netherite_scrap": {
        "name": "Netherite Scrap",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Smelt ancient debris"],
        "uses": ["Craft netherite ingots"],
    },
    "minecraft:netherite_ingot": {
        "name": "Netherite Ingot",
        "kind": "item",
        "stack_size": 64,
        "obtained_from": ["Crafted from netherite scraps and gold ingots"],
        "uses": ["Smithing upgrades for diamond gear", "Lodestones"],
    },
}


RECIPES: dict[str, dict[str, Any]] = {
    "minecraft:oak_planks": {
        "station": "2x2 or 3x3 crafting grid",
        "ingredients": [{"item": "#minecraft:logs", "count": 1}],
        "result": {"item": "minecraft:oak_planks", "count": 4},
        "notes": ["The resulting plank type follows the input log type."],
    },
    "minecraft:crafting_table": {
        "station": "2x2 or 3x3 crafting grid",
        "pattern": ["PP", "PP"],
        "ingredients": [{"item": "#minecraft:planks", "count": 4}],
        "result": {"item": "minecraft:crafting_table", "count": 1},
    },
    "minecraft:stick": {
        "station": "2x2 or 3x3 crafting grid",
        "pattern": ["P", "P"],
        "ingredients": [{"item": "#minecraft:planks", "count": 2}],
        "result": {"item": "minecraft:stick", "count": 4},
    },
    "minecraft:torch": {
        "station": "2x2 or 3x3 crafting grid",
        "pattern": ["C", "S"],
        "ingredients": [{"item": "minecraft:coal or minecraft:charcoal", "count": 1}, {"item": "minecraft:stick", "count": 1}],
        "result": {"item": "minecraft:torch", "count": 4},
    },
    "minecraft:chest": {
        "station": "3x3 crafting grid",
        "pattern": ["PPP", "P P", "PPP"],
        "ingredients": [{"item": "#minecraft:planks", "count": 8}],
        "result": {"item": "minecraft:chest", "count": 1},
    },
    "minecraft:furnace": {
        "station": "3x3 crafting grid",
        "pattern": ["CCC", "C C", "CCC"],
        "ingredients": [{"item": "minecraft:cobblestone or minecraft:blackstone or minecraft:cobbled_deepslate", "count": 8}],
        "result": {"item": "minecraft:furnace", "count": 1},
    },
    "minecraft:stone_pickaxe": {
        "station": "3x3 crafting grid",
        "pattern": ["CCC", " S ", " S "],
        "ingredients": [{"item": "stone-tier material", "count": 3}, {"item": "minecraft:stick", "count": 2}],
        "result": {"item": "minecraft:stone_pickaxe", "count": 1},
    },
    "minecraft:iron_pickaxe": {
        "station": "3x3 crafting grid",
        "pattern": ["III", " S ", " S "],
        "ingredients": [{"item": "minecraft:iron_ingot", "count": 3}, {"item": "minecraft:stick", "count": 2}],
        "result": {"item": "minecraft:iron_pickaxe", "count": 1},
    },
    "minecraft:diamond_pickaxe": {
        "station": "3x3 crafting grid",
        "pattern": ["DDD", " S ", " S "],
        "ingredients": [{"item": "minecraft:diamond", "count": 3}, {"item": "minecraft:stick", "count": 2}],
        "result": {"item": "minecraft:diamond_pickaxe", "count": 1},
    },
    "minecraft:bucket": {
        "station": "3x3 crafting grid",
        "pattern": ["I I", " I "],
        "ingredients": [{"item": "minecraft:iron_ingot", "count": 3}],
        "result": {"item": "minecraft:bucket", "count": 1},
    },
    "minecraft:compass": {
        "station": "3x3 crafting grid",
        "pattern": [" I ", "IRI", " I "],
        "ingredients": [{"item": "minecraft:iron_ingot", "count": 4}, {"item": "minecraft:redstone", "count": 1}],
        "result": {"item": "minecraft:compass", "count": 1},
    },
    "minecraft:paper": {
        "station": "3x3 crafting grid",
        "pattern": ["SSS"],
        "ingredients": [{"item": "minecraft:sugar_cane", "count": 3}],
        "result": {"item": "minecraft:paper", "count": 3},
    },
    "minecraft:book": {
        "station": "3x3 crafting grid",
        "ingredients": [{"item": "minecraft:paper", "count": 3}, {"item": "minecraft:leather", "count": 1}],
        "result": {"item": "minecraft:book", "count": 1},
    },
    "minecraft:white_bed": {
        "station": "3x3 crafting grid",
        "pattern": ["WWW", "PPP"],
        "ingredients": [{"item": "minecraft:white_wool", "count": 3}, {"item": "#minecraft:planks", "count": 3}],
        "result": {"item": "minecraft:white_bed", "count": 1},
        "notes": ["Other bed colors use matching wool colors."],
    },
    "minecraft:bread": {
        "station": "3x3 crafting grid",
        "pattern": ["WWW"],
        "ingredients": [{"item": "minecraft:wheat", "count": 3}],
        "result": {"item": "minecraft:bread", "count": 1},
    },
    "minecraft:shield": {
        "station": "3x3 crafting grid",
        "pattern": ["PIP", "PPP", " P "],
        "ingredients": [{"item": "#minecraft:planks", "count": 6}, {"item": "minecraft:iron_ingot", "count": 1}],
        "result": {"item": "minecraft:shield", "count": 1},
    },
    "minecraft:netherite_ingot": {
        "station": "3x3 crafting grid",
        "ingredients": [{"item": "minecraft:netherite_scrap", "count": 4}, {"item": "minecraft:gold_ingot", "count": 4}],
        "result": {"item": "minecraft:netherite_ingot", "count": 1},
    },
}


def lookup_item(query: str) -> dict[str, Any]:
    item_id = canonical_item_id(query)
    item = ITEMS.get(item_id)
    if item is None:
        return _not_found(query, "item")
    payload = {"ok": True, "found": True, "item": item_id}
    payload.update(item)
    recipe = RECIPES.get(item_id)
    if recipe is not None:
        payload["has_known_recipe"] = True
    return payload


def lookup_recipe(query: str) -> dict[str, Any]:
    item_id = canonical_item_id(query)
    recipe = RECIPES.get(item_id)
    if recipe is None:
        payload = _not_found(query, "recipe")
        item = ITEMS.get(item_id)
        if item is not None:
            payload["known_item"] = {"item": item_id, "name": item.get("name"), "notes": item.get("notes", [])}
        return payload
    payload = {"ok": True, "found": True, "item": item_id, "name": ITEMS.get(item_id, {}).get("name", item_id)}
    payload.update(recipe)
    return payload


def canonical_item_id(query: str) -> str:
    value = str(query or "").strip().lower()
    value = ALIASES.get(value, value)
    value = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’]+$", "", value)
    value = value.replace(" ", "_").replace("-", "_")
    if ":" not in value:
        value = "minecraft:" + value
    return value


def _not_found(query: str, kind: str) -> dict[str, Any]:
    normalized = canonical_item_id(query)
    needle = normalized.split(":", 1)[-1]
    suggestions = [
        item_id
        for item_id, item in ITEMS.items()
        if needle and (needle in item_id or needle in str(item.get("name", "")).lower().replace(" ", "_"))
    ][:8]
    if not suggestions:
        suggestions = sorted(ITEMS)[:8]
    return {
        "ok": True,
        "found": False,
        "query": str(query or ""),
        "canonical_item": normalized,
        "kind": kind,
        "suggestions": suggestions,
        "note": "The built-in lookup is intentionally small; use minecraft_wiki_search for uncommon or version-sensitive items.",
    }
