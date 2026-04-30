package com.mina.game;

import com.google.gson.Gson;
import com.mina.config.MinaConfig;
import com.mojang.brigadier.arguments.StringArgumentType;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.permissions.PermissionSet;
import net.minecraft.world.effect.MobEffectInstance;
import net.minecraft.world.effect.MobEffects;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.gamerules.GameRules;
import net.minecraft.world.phys.AABB;

import static net.minecraft.commands.Commands.argument;
import static net.minecraft.commands.Commands.literal;

public final class MinaTestCommands {
	private static final Gson GSON = new Gson();
	private static final String TEST_PLAYER = "mina_tester";
	private static final int TREE_X = 2;
	private static final int TREE_Y = 80;
	private static final int TREE_Z = 0;
	private static final int FIXTURE_RADIUS = 20;
	private static final int FIXTURE_CLEAR_DOWN = 4;
	private static final int FIXTURE_CLEAR_UP = 12;
	private static final BlockPos TARGET_LOG = new BlockPos(TREE_X, TREE_Y, TREE_Z);
	private static final BlockPos UPPER_LOG = new BlockPos(TREE_X, TREE_Y + 1, TREE_Z);
	private static final BlockPos SETUP_MARKER = new BlockPos(0, TREE_Y - 1, 0);

	private final MinaConfig config;
	private final MinaSnapshotter snapshotter;
	private final MinaTurnController turnController;

	public MinaTestCommands(MinaConfig config, MinaSnapshotter snapshotter, MinaTurnController turnController) {
		this.config = config;
		this.snapshotter = snapshotter;
		this.turnController = turnController;
	}

	public void register() {
		if (!Boolean.getBoolean("mina.testHarness")) {
			return;
		}
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
			literal("mina-test")
				.then(literal("setup")
					.then(literal("default_world").executes(context -> setupDefaultWorld(context.getSource())))
					.then(literal("tree_world").executes(context -> setupTreeWorld(context.getSource()))))
				.then(literal("request")
					.then(argument("content", StringArgumentType.greedyString())
						.executes(context -> request(context.getSource(), StringArgumentType.getString(context, "content")))))
				.then(literal("request_with_id")
					.then(argument("request_id", StringArgumentType.word())
						.then(argument("content", StringArgumentType.greedyString())
							.executes(context -> requestWithId(
								context.getSource(),
								StringArgumentType.getString(context, "request_id"),
								StringArgumentType.getString(context, "content")
							)))))
				.then(literal("companion_tick_with_id")
					.then(argument("request_id", StringArgumentType.word())
						.executes(context -> companionTickWithId(
							context.getSource(),
							StringArgumentType.getString(context, "request_id")
						))))
				.then(literal("fixture")
					.then(literal("reset")
						.then(argument("name", StringArgumentType.word())
							.executes(context -> fixtureReset(context.getSource(), StringArgumentType.getString(context, "name"))))))
				.then(literal("world")
					.then(literal("mutate")
						.then(argument("operation", StringArgumentType.word())
							.executes(context -> worldMutate(context.getSource(), StringArgumentType.getString(context, "operation"))))))
				.then(literal("ready").executes(context -> ready(context.getSource())))
				.then(literal("deny_actions").executes(context -> denyActions(context.getSource())))
				.then(literal("allow_actions").executes(context -> allowActions(context.getSource())))
				.then(literal("move_requester_far").executes(context -> moveRequesterFar(context.getSource())))
				.then(literal("move_requester_far_again").executes(context -> moveRequesterFarAgain(context.getSource())))
				.then(literal("remove_target_log").executes(context -> removeTargetLog(context.getSource())))
				.then(literal("snapshot").executes(context -> snapshot(context.getSource())))
				.then(literal("assert")
					.then(literal("target_log_present").executes(context -> assertTargetLogPresent(context.getSource())))
					.then(literal("upper_log_present").executes(context -> assertUpperLogPresent(context.getSource())))
					.then(literal("low_health").executes(context -> assertLowHealth(context.getSource())))
					.then(literal("no_nearby_entities").executes(context -> assertNoNearbyEntities(context.getSource()))))
		));
	}

	private int setupDefaultWorld(CommandSourceStack source) {
		setupWorldAndRequester(source, false);
		source.sendSuccess(() -> Component.literal("Mina test default_world setup complete. Poll /mina-test ready before requesting."), false);
		return 1;
	}

	private int setupTreeWorld(CommandSourceStack source) {
		setupWorldAndRequester(source, true);
		source.sendSuccess(() -> Component.literal("Mina test tree_world setup complete. Poll /mina-test ready before requesting."), false);
		return 1;
	}

	private int fixtureReset(CommandSourceStack source, String name) {
		return switch (name) {
			case "default_world" -> {
				setupWorldAndRequester(source, false);
				source.sendSuccess(() -> Component.literal("Mina test fixture default_world reset complete. Poll /mina-test ready before requesting."), false);
				yield 1;
			}
			case "tree_world" -> {
				setupWorldAndRequester(source, true);
				source.sendSuccess(() -> Component.literal("Mina test fixture tree_world reset complete. Poll /mina-test ready before requesting."), false);
				yield 1;
			}
			default -> {
				source.sendFailure(Component.literal("Unknown Mina test fixture: " + name));
				yield 0;
			}
		};
	}

	private void setupWorldAndRequester(CommandSourceStack source, boolean includeTree) {
		MinecraftServer server = source.getServer();
		ServerLevel level = source.getLevel();
		prepareWorld(level, includeTree);
		run(server, "difficulty peaceful");
		setNaturalHealthRegeneration(level, server, true);
		setMobSpawning(level, server, false);
		clearNonPlayerEntities(server);
		run(server, "time set day");
		run(server, "weather clear");
		run(server, "puppet " + TEST_PLAYER + " spawn");
		config.allow(TEST_PLAYER);
	}

	private int ready(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		MinecraftServer server = source.getServer();
		ServerPlayer requester = server.getPlayerList().getPlayer(TEST_PLAYER);
		boolean markerReady = level.getBlockState(SETUP_MARKER).is(Blocks.GRASS_BLOCK);
		if (requester != null) {
			run(server, "tp " + TEST_PLAYER + " 0.5 " + TREE_Y + " -2.5 0 0");
			clearNonPlayerEntities(server);
			clearNearbyNonPlayerEntities(level, requester);
			resetVitals(requester);
			resetRequesterInventory(requester);
		}
		if (!markerReady || requester == null) {
			source.sendFailure(Component.literal(
				"Mina test not ready: marker=" + markerReady
					+ ", requester_online=" + (requester != null)
			));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test ready."), false);
		return 1;
	}

	private int denyActions(CommandSourceStack source) {
		config.deny(TEST_PLAYER);
		run(source.getServer(), "deop " + TEST_PLAYER);
		source.sendSuccess(() -> Component.literal("Mina test actions denied for " + TEST_PLAYER + "."), false);
		return 1;
	}

	private int allowActions(CommandSourceStack source) {
		config.allow(TEST_PLAYER);
		source.sendSuccess(() -> Component.literal("Mina test actions allowed for " + TEST_PLAYER + "."), false);
		return 1;
	}

	private int request(CommandSourceStack source, String content) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online. Run /mina-test setup first."));
			return 0;
		}
		return turnController.submitPlayerTurn(source.getServer(), requester, "command", content, false);
	}

	private int requestWithId(CommandSourceStack source, String requestId, String content) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online. Run /mina-test fixture reset first."));
			return 0;
		}
		return turnController.submitPlayerTurn(source.getServer(), requester, "command", content, false, requestId);
	}

	private int companionTickWithId(CommandSourceStack source, String requestId) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online. Run /mina-test fixture reset first."));
			return 0;
		}
		return turnController.submitPlayerTurn(source.getServer(), requester, "companion_tick", "", false, requestId);
	}

	private int worldMutate(CommandSourceStack source, String operation) {
		return switch (operation) {
			case "remove_target_log" -> removeTargetLog(source);
			case "move_requester_far" -> moveRequesterFar(source);
			case "move_requester_far_again" -> moveRequesterFarAgain(source);
			case "deny_actions" -> denyActions(source);
			case "allow_actions" -> allowActions(source);
			case "day" -> {
				run(source.getServer(), "time set day");
				source.sendSuccess(() -> Component.literal("Mina test world mutate day complete."), false);
				yield 1;
			}
			case "clear_weather" -> {
				run(source.getServer(), "weather clear");
				source.sendSuccess(() -> Component.literal("Mina test world mutate clear_weather complete."), false);
				yield 1;
			}
			case "low_health" -> lowHealth(source);
			case "low_hunger" -> lowHunger(source);
			case "poisoned" -> poisoned(source);
			case "on_fire" -> onFire(source);
			case "nearby_hostile" -> nearbyHostile(source);
			case "nearby_passive_mob" -> nearbyPassiveMob(source);
			case "nearby_item_drop" -> nearbyItemDrop(source);
			case "inventory_sample" -> inventorySample(source);
			case "grant_eye_spy_advancement" -> grantEyeSpyAdvancement(source);
			default -> {
				source.sendFailure(Component.literal("Unknown Mina test world mutate operation: " + operation));
				yield 0;
			}
		};
	}

	private int moveRequesterFar(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		run(source.getServer(), "tp " + TEST_PLAYER + " 4.5 " + TREE_Y + " -4.5 0 0");
		source.sendSuccess(() -> Component.literal("Mina test requester moved far."), false);
		return 1;
	}

	private int moveRequesterFarAgain(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		run(source.getServer(), "tp " + TEST_PLAYER + " -4.5 " + TREE_Y + " 4.5 0 0");
		source.sendSuccess(() -> Component.literal("Mina test requester moved far again."), false);
		return 1;
	}

	private int removeTargetLog(CommandSourceStack source) {
		source.getLevel().setBlock(TARGET_LOG, Blocks.AIR.defaultBlockState(), 3);
		source.sendSuccess(() -> Component.literal("Mina test target log removed."), false);
		return 1;
	}

	private int lowHealth(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		setNaturalHealthRegeneration(source.getLevel(), source.getServer(), false);
		requester.getFoodData().setFoodLevel(20);
		requester.getFoodData().setSaturation(5.0F);
		requester.setHealth(4.0F);
		source.sendSuccess(() -> Component.literal("Mina test world mutate low_health complete."), false);
		return 1;
	}

	private int grantEyeSpyAdvancement(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		run(source.getServer(), "advancement grant " + TEST_PLAYER + " only minecraft:story/follow_ender_eye");
		source.sendSuccess(() -> Component.literal("Mina test world mutate grant_eye_spy_advancement complete."), false);
		return 1;
	}

	private int lowHunger(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		run(source.getServer(), "difficulty normal");
		requester.getFoodData().setFoodLevel(4);
		requester.getFoodData().setSaturation(0.0F);
		source.sendSuccess(() -> Component.literal("Mina test world mutate low_hunger complete."), false);
		return 1;
	}

	private int poisoned(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		requester.addEffect(new MobEffectInstance(MobEffects.POISON, 200, 0));
		source.sendSuccess(() -> Component.literal("Mina test world mutate poisoned complete."), false);
		return 1;
	}

	private int onFire(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		requester.setRemainingFireTicks(200);
		source.sendSuccess(() -> Component.literal("Mina test world mutate on_fire complete."), false);
		return 1;
	}

	private int nearbyHostile(CommandSourceStack source) {
		run(source.getServer(), "difficulty normal");
		run(source.getServer(), "summon minecraft:creeper 1.5 " + TREE_Y + " -2.5 {NoAI:1b,Silent:1b,PersistenceRequired:1b}");
		source.sendSuccess(() -> Component.literal("Mina test world mutate nearby_hostile complete."), false);
		return 1;
	}

	private int nearbyPassiveMob(CommandSourceStack source) {
		run(source.getServer(), "summon minecraft:sheep 2.5 " + TREE_Y + " -2.5 {NoAI:1b,Silent:1b,PersistenceRequired:1b}");
		source.sendSuccess(() -> Component.literal("Mina test world mutate nearby_passive_mob complete."), false);
		return 1;
	}

	private int nearbyItemDrop(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		ItemEntity item = new ItemEntity(level, 3.5D, TREE_Y, -2.5D, new ItemStack(Items.OAK_LOG, 2));
		item.setPickUpDelay(32767);
		item.setNoGravity(true);
		level.addFreshEntity(item);
		source.sendSuccess(() -> Component.literal("Mina test world mutate nearby_item_drop complete."), false);
		return 1;
	}

	private int inventorySample(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		int selectedSlot = requester.getInventory().getSelectedSlot();
		int appleSlot = selectedSlot == 1 ? 2 : 1;
		requester.getInventory().clearContent();
		requester.getInventory().setItem(selectedSlot, new ItemStack(Items.GUNPOWDER, 1));
		requester.getInventory().setItem(appleSlot, new ItemStack(Items.APPLE, 3));
		source.sendSuccess(() -> Component.literal("Mina test world mutate inventory_sample complete."), false);
		return 1;
	}

	private void resetVitals(ServerPlayer player) {
		player.setHealth(player.getMaxHealth());
		player.getFoodData().setFoodLevel(20);
		player.getFoodData().setSaturation(5.0F);
		player.removeAllEffects();
		player.clearFire();
	}

	private void resetRequesterInventory(ServerPlayer player) {
		int selectedSlot = player.getInventory().getSelectedSlot();
		player.getInventory().clearContent();
		player.getInventory().setItem(selectedSlot, new ItemStack(Items.GUNPOWDER, 1));
	}

	private int snapshot(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal(GSON.toJson(snapshotter.createTurnPayload(source.getServer(), requester, config, "test_snapshot", "", "mina-test"))), false);
		return 1;
	}

	private int assertTargetLogPresent(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		boolean present = level.getBlockState(TARGET_LOG).is(Blocks.SPRUCE_LOG);
		if (!present) {
			source.sendFailure(Component.literal("Mina test target_log_present failed: target log was changed."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test target_log_present passed."), false);
		return 1;
	}

	private int assertUpperLogPresent(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		boolean present = level.getBlockState(UPPER_LOG).is(Blocks.SPRUCE_LOG);
		if (!present) {
			source.sendFailure(Component.literal("Mina test upper_log_present failed: upper log was changed."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test upper_log_present passed."), false);
		return 1;
	}

	private int assertLowHealth(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Mina test low_health failed: test requester is not online."));
			return 0;
		}
		float health = requester.getHealth();
		if (health > 4.5F) {
			source.sendFailure(Component.literal("Mina test low_health failed: health was " + health + "."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test low_health passed."), false);
		return 1;
	}

	private int assertNoNearbyEntities(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Mina test no_nearby_entities failed: test requester is not online."));
			return 0;
		}
		clearNearbyNonPlayerEntities(source.getLevel(), requester);
		AABB box = requester.getBoundingBox().inflate(config.nearbyEntityRadius);
		var entities = source.getLevel().getEntities(
			requester,
			box,
			entity -> entity.isAlive() && !(entity instanceof Player)
		);
		if (!entities.isEmpty()) {
			source.sendFailure(Component.literal("Mina test no_nearby_entities failed: found " + entities.size() + " nearby non-player entities."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test no_nearby_entities passed."), false);
		return 1;
	}

	private void clearNearbyNonPlayerEntities(ServerLevel level, ServerPlayer requester) {
		AABB box = requester.getBoundingBox().inflate(config.nearbyEntityRadius);
		var entities = level.getEntities(
			requester,
			box,
			entity -> entity.isAlive() && !(entity instanceof Player)
		);
		for (var entity : entities) {
			entity.discard();
		}
	}

	private static void run(MinecraftServer server, String command) {
		server.getCommands().performPrefixedCommand(
			server.createCommandSourceStack().withMaximumPermission(PermissionSet.ALL_PERMISSIONS),
			command
		);
	}

	private static void clearNonPlayerEntities(MinecraftServer server) {
		run(server, "kill @e[type=!minecraft:player]");
	}

	private static void setNaturalHealthRegeneration(ServerLevel level, MinecraftServer server, boolean enabled) {
		level.getGameRules().set(GameRules.NATURAL_HEALTH_REGENERATION, enabled, server);
	}

	private static void setMobSpawning(ServerLevel level, MinecraftServer server, boolean enabled) {
		level.getGameRules().set(GameRules.SPAWN_MOBS, enabled, server);
	}

	private static void prepareWorld(ServerLevel level, boolean includeTree) {
		int minChunk = Math.floorDiv(-FIXTURE_RADIUS, 16);
		int maxChunk = Math.floorDiv(FIXTURE_RADIUS, 16);
		for (int chunkX = minChunk; chunkX <= maxChunk; chunkX++) {
			for (int chunkZ = minChunk; chunkZ <= maxChunk; chunkZ++) {
				level.setChunkForced(chunkX, chunkZ, true);
				level.getChunk(chunkX, chunkZ);
			}
		}
		for (int x = -FIXTURE_RADIUS; x <= FIXTURE_RADIUS; x++) {
			for (int z = -FIXTURE_RADIUS; z <= FIXTURE_RADIUS; z++) {
				level.setBlock(new BlockPos(x, TREE_Y - 1, z), Blocks.GRASS_BLOCK.defaultBlockState(), 3);
				for (int y = TREE_Y - FIXTURE_CLEAR_DOWN; y <= TREE_Y + FIXTURE_CLEAR_UP; y++) {
					if (y == TREE_Y - 1) {
						continue;
					}
					level.setBlock(new BlockPos(x, y, z), Blocks.AIR.defaultBlockState(), 3);
				}
			}
		}
		clearSkyColumnsAroundRequester(level);
		level.setBlock(SETUP_MARKER, Blocks.GRASS_BLOCK.defaultBlockState(), 3);
		if (!includeTree) {
			return;
		}
		level.setBlock(TARGET_LOG, Blocks.SPRUCE_LOG.defaultBlockState(), 3);
		level.setBlock(UPPER_LOG, Blocks.SPRUCE_LOG.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X + 1, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X - 1, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z + 1), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z - 1), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
	}

	private static void clearSkyColumn(ServerLevel level, BlockPos pos) {
		for (int y = pos.getY(); y < level.getMaxY(); y++) {
			level.setBlock(new BlockPos(pos.getX(), y, pos.getZ()), Blocks.AIR.defaultBlockState(), 3);
		}
	}

	private static void clearSkyColumnsAroundRequester(ServerLevel level) {
		for (int x = -1; x <= 1; x++) {
			for (int z = -4; z <= -2; z++) {
				clearSkyColumn(level, new BlockPos(x, TREE_Y, z));
			}
		}
	}
}
