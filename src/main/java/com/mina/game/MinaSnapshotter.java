package com.mina.game;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mina.config.MinaConfig;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.tags.BlockTags;
import net.minecraft.tags.ItemTags;
import net.minecraft.world.effect.MobEffectInstance;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.player.Inventory;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.AABB;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class MinaSnapshotter {
	public JsonObject createTurnPayload(
		MinecraftServer server,
		ServerPlayer player,
		MinaConfig config,
		String trigger,
		String message,
		String requestId
	) {
		JsonObject payload = new JsonObject();
		payload.addProperty("request_id", requestId);
		payload.addProperty("server_id", server.getServerModName());
		payload.addProperty("world_id", server.getWorldData().getLevelName());
		payload.addProperty("trigger", trigger);
		payload.addProperty("message", message == null ? "" : message);
		payload.add("player", player(player, server, config));
		payload.add("permissions", permissions(player, server, config));
		payload.add("snapshot", snapshot(server, player, config));
		payload.add("recent_events", new JsonArray());
		return payload;
	}

	public JsonObject snapshot(MinecraftServer server, ServerPlayer player, MinaConfig config) {
		ServerLevel level = player.level();
		JsonObject snapshot = new JsonObject();
		snapshot.add("player_state", playerState(player));
		snapshot.add("world_state", worldState(server, level, player));
		snapshot.add("inventory", inventory(player, config));
		snapshot.add("nearby_entities", nearbyEntities(level, player, config));
		snapshot.add("nearby_blocks", nearbyBlocks(level, player));
		snapshot.add("environment", environment(level, player));
		return snapshot;
	}

	private JsonObject player(ServerPlayer player, MinecraftServer server, MinaConfig config) {
		JsonObject json = new JsonObject();
		json.addProperty("uuid", player.getUUID().toString());
		json.addProperty("name", player.getGameProfile().name());
		json.addProperty("is_op", server.getPlayerList().isOp(player.nameAndId()));
		json.addProperty("can_use_actions", config.canUseActions(server, player));
		return json;
	}

	private JsonObject permissions(ServerPlayer player, MinecraftServer server, MinaConfig config) {
		JsonObject json = new JsonObject();
		json.addProperty("can_use_actions", config.canUseActions(server, player));
		return json;
	}

	private JsonObject playerState(ServerPlayer player) {
		JsonObject json = new JsonObject();
		json.addProperty("health", player.getHealth());
		json.addProperty("max_health", player.getMaxHealth());
		json.addProperty("armor", player.getArmorValue());
		json.addProperty("food", player.getFoodData().getFoodLevel());
		json.addProperty("saturation", player.getFoodData().getSaturationLevel());
		json.addProperty("experience_level", player.experienceLevel);
		json.addProperty("total_experience", player.totalExperience);
		json.addProperty("game_mode", player.gameMode().getName());
		json.addProperty("dimension", player.level().dimension().identifier().toString());
		json.addProperty("x", round(player.getX()));
		json.addProperty("y", round(player.getY()));
		json.addProperty("z", round(player.getZ()));
		json.addProperty("yaw", round(player.getYRot()));
		json.addProperty("pitch", round(player.getXRot()));
		json.addProperty("on_ground", player.onGround());
		json.addProperty("in_lava", player.isInLava());
		json.addProperty("underwater", player.isUnderWater());
		json.addProperty("on_fire", player.isOnFire());
		json.add("effects", effects(player));
		return json;
	}

	private JsonObject worldState(MinecraftServer server, ServerLevel level, ServerPlayer player) {
		JsonObject json = new JsonObject();
		json.addProperty("day_time", level.getDayTime());
		json.addProperty("day_count", level.getDayCount());
		json.addProperty("difficulty", level.getDifficulty().getKey());
		json.addProperty("raining", level.isRaining());
		json.addProperty("thundering", level.isThundering());
		json.addProperty("dimension", level.dimension().identifier().toString());
		json.addProperty("seed", level.getSeed());
		BlockPos spawn = level.getLevelData().getRespawnData().pos();
		json.addProperty("spawn_x", spawn.getX());
		json.addProperty("spawn_y", spawn.getY());
		json.addProperty("spawn_z", spawn.getZ());
		json.addProperty("online_players", server.getPlayerList().getPlayerCount());
		json.add("online_player_names", onlinePlayerNames(server));
		json.addProperty("pvp_allowed", level.isPvpAllowed());
		json.addProperty("command_blocks_enabled", level.isCommandBlockEnabled());
		json.addProperty("player_distance_from_spawn", round(Math.sqrt(player.blockPosition().distSqr(spawn))));
		return json;
	}

	private JsonArray onlinePlayerNames(MinecraftServer server) {
		JsonArray array = new JsonArray();
		for (ServerPlayer onlinePlayer : server.getPlayerList().getPlayers()) {
			array.add(onlinePlayer.getGameProfile().name());
		}
		return array;
	}

	private JsonArray inventory(ServerPlayer player, MinaConfig config) {
		JsonArray array = new JsonArray();
		Inventory inventory = player.getInventory();
		int limit = Math.min(inventory.getContainerSize(), config.maxInventorySlotsReported);
		for (int slot = 0; slot < limit; slot++) {
			ItemStack stack = inventory.getItem(slot);
			if (stack.isEmpty()) {
				continue;
			}
			JsonObject item = new JsonObject();
			item.addProperty("slot", slot);
			item.addProperty("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
			item.addProperty("count", stack.getCount());
			item.addProperty("name", stack.getHoverName().getString());
			item.addProperty("selected", slot == inventory.getSelectedSlot());
			array.add(item);
		}
		ItemStack offhand = player.getOffhandItem();
		if (!offhand.isEmpty()) {
			JsonObject item = new JsonObject();
			item.addProperty("slot", "offhand");
			item.addProperty("item", BuiltInRegistries.ITEM.getKey(offhand.getItem()).toString());
			item.addProperty("count", offhand.getCount());
			item.addProperty("name", offhand.getHoverName().getString());
			array.add(item);
		}
		return array;
	}

	private JsonArray nearbyEntities(ServerLevel level, Entity anchor, MinaConfig config) {
		AABB box = anchor.getBoundingBox().inflate(config.nearbyEntityRadius);
		List<Entity> entities = level.getEntities(anchor, box, entity -> entity.isAlive() && entity != anchor);
		entities.sort(Comparator.comparingDouble(anchor::distanceToSqr));

		JsonArray array = new JsonArray();
		int count = 0;
		for (Entity entity : entities) {
			if (count >= config.maxNearbyEntitiesReported) {
				break;
			}
			JsonObject json = new JsonObject();
			json.addProperty("id", entity.getStringUUID());
			json.addProperty("type", BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());
			json.addProperty("name", entity.getName().getString());
			json.addProperty("category", category(entity));
			json.addProperty("distance", round(Math.sqrt(anchor.distanceToSqr(entity))));
			json.addProperty("x", round(entity.getX()));
			json.addProperty("y", round(entity.getY()));
			json.addProperty("z", round(entity.getZ()));
			if (entity instanceof LivingEntity living) {
				json.addProperty("health", living.getHealth());
				json.addProperty("max_health", living.getMaxHealth());
			}
			if (entity instanceof ItemEntity itemEntity) {
				ItemStack stack = itemEntity.getItem();
				json.addProperty("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
				json.addProperty("count", stack.getCount());
				if (stack.is(ItemTags.LOGS)) {
					json.addProperty("item_category", "log");
				}
			}
			array.add(json);
			count++;
		}
		return array;
	}

	private JsonObject environment(ServerLevel level, ServerPlayer player) {
		BlockPos pos = player.blockPosition();
		JsonObject json = new JsonObject();
		json.addProperty("block_at_feet", BuiltInRegistries.BLOCK.getKey(level.getBlockState(pos).getBlock()).toString());
		json.addProperty("block_below", BuiltInRegistries.BLOCK.getKey(level.getBlockState(pos.below()).getBlock()).toString());
		json.addProperty("sky_visible", level.canSeeSkyFromBelowWater(pos));
		json.addProperty("light", level.getMaxLocalRawBrightness(pos));
		String biome = level.getBiome(pos).unwrapKey().map(key -> key.identifier().toString()).orElse("unknown");
		json.addProperty("biome", biome);
		return json;
	}

	private JsonObject nearbyBlocks(ServerLevel level, ServerPlayer player) {
		JsonObject json = new JsonObject();
		json.add("requester", nearbyBlocksAround(level, player.blockPosition()));
		return json;
	}

	private JsonArray nearbyBlocksAround(ServerLevel level, BlockPos center) {
		int horizontalRadius = 12;
		int down = 4;
		int up = 8;
		List<JsonObject> blocks = new ArrayList<>();
		for (BlockPos pos : BlockPos.betweenClosed(
			center.offset(-horizontalRadius, -down, -horizontalRadius),
			center.offset(horizontalRadius, up, horizontalRadius)
		)) {
			if (!level.isLoaded(pos)) {
				continue;
			}
			BlockState state = level.getBlockState(pos);
			String category = interestingBlockCategory(state);
			if (category == null) {
				continue;
			}
			JsonObject block = new JsonObject();
			block.addProperty("block", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
			block.addProperty("category", category);
			block.addProperty("x", pos.getX());
			block.addProperty("y", pos.getY());
			block.addProperty("z", pos.getZ());
			block.addProperty("center_x", pos.getX() + 0.5D);
			block.addProperty("center_y", pos.getY() + 0.5D);
			block.addProperty("center_z", pos.getZ() + 0.5D);
			block.addProperty("distance", round(Math.sqrt(center.distSqr(pos))));
			BlockPos approach = findApproachPosition(level, pos);
			if (approach != null) {
				block.addProperty("approach_x", approach.getX() + 0.5D);
				block.addProperty("approach_y", approach.getY());
				block.addProperty("approach_z", approach.getZ() + 0.5D);
			}
			blocks.add(block);
		}
		blocks.sort(Comparator.comparingDouble(json -> json.get("distance").getAsDouble()));
		JsonArray array = new JsonArray();
		List<JsonObject> selected = new ArrayList<>();
		appendCategoryBlocks(selected, blocks, "log", 40, 80);
		appendCategoryBlocks(selected, blocks, "ore", 20, 80);
		appendCategoryBlocks(selected, blocks, "crop", 20, 80);
		appendRemainingBlocks(selected, blocks, 80);
		for (JsonObject block : selected) {
			array.add(block);
		}
		return array;
	}

	private static void appendCategoryBlocks(List<JsonObject> selected, List<JsonObject> blocks, String category, int categoryLimit, int totalLimit) {
		int count = 0;
		for (JsonObject block : blocks) {
			if (selected.size() >= totalLimit || count >= categoryLimit) {
				return;
			}
			if (category.equals(block.get("category").getAsString()) && !selected.contains(block)) {
				selected.add(block);
				count++;
			}
		}
	}

	private static void appendRemainingBlocks(List<JsonObject> selected, List<JsonObject> blocks, int totalLimit) {
		for (JsonObject block : blocks) {
			if (selected.size() >= totalLimit) {
				return;
			}
			if (!selected.contains(block)) {
				selected.add(block);
			}
		}
	}

	private JsonArray effects(LivingEntity entity) {
		JsonArray array = new JsonArray();
		for (MobEffectInstance effect : entity.getActiveEffects()) {
			JsonObject json = new JsonObject();
			json.addProperty("id", BuiltInRegistries.MOB_EFFECT.getKey(effect.getEffect().value()).toString());
			json.addProperty("effect", effect.getDescriptionId());
			json.addProperty("duration", effect.getDuration());
			json.addProperty("amplifier", effect.getAmplifier());
			array.add(json);
		}
		return array;
	}

	private static String category(Entity entity) {
		if (entity instanceof Player) {
			return "player";
		}
		MobCategory category = entity.getType().getCategory();
		if (category == MobCategory.MONSTER) {
			return "hostile";
		}
		if (category.isFriendly()) {
			return "passive";
		}
		if (category == MobCategory.MISC) {
			return "misc";
		}
		return "neutral";
	}

	private static String interestingBlockCategory(BlockState state) {
		if (state.is(BlockTags.LOGS)) {
			return "log";
		}
		if (state.is(BlockTags.LEAVES)) {
			return "leaves";
		}
		if (state.is(BlockTags.CROPS)) {
			return "crop";
		}
		if (isOre(state)) {
			return "ore";
		}
		return null;
	}

	private static boolean isOre(BlockState state) {
		return state.is(BlockTags.COAL_ORES)
			|| state.is(BlockTags.COPPER_ORES)
			|| state.is(BlockTags.IRON_ORES)
			|| state.is(BlockTags.GOLD_ORES)
			|| state.is(BlockTags.REDSTONE_ORES)
			|| state.is(BlockTags.LAPIS_ORES)
			|| state.is(BlockTags.EMERALD_ORES)
			|| state.is(BlockTags.DIAMOND_ORES);
	}

	private static BlockPos findApproachPosition(ServerLevel level, BlockPos target) {
		BlockPos[] candidates = {
			target.north(),
			target.south(),
			target.east(),
			target.west()
		};
		for (BlockPos candidate : candidates) {
			if (level.getBlockState(candidate).isAir()
				&& level.getBlockState(candidate.above()).isAir()
				&& !level.getBlockState(candidate.below()).isAir()) {
				return candidate;
			}
		}
		return null;
	}

	private static double round(double value) {
		return Math.round(value * 100.0D) / 100.0D;
	}
}
