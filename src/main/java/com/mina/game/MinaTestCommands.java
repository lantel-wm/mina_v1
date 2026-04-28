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
import net.minecraft.world.level.block.Blocks;

import java.util.regex.Pattern;

import static net.minecraft.commands.Commands.argument;
import static net.minecraft.commands.Commands.literal;

public final class MinaTestCommands {
	private static final Gson GSON = new Gson();
	private static final String TEST_PLAYER = "mina_tester";
	private static final int TREE_X = 2;
	private static final int TREE_Y = 80;
	private static final int TREE_Z = 0;
	private static final BlockPos TARGET_LOG = new BlockPos(TREE_X, TREE_Y, TREE_Z);
	private static final BlockPos UPPER_LOG = new BlockPos(TREE_X, TREE_Y + 1, TREE_Z);
	private static final BlockPos SETUP_MARKER = new BlockPos(0, TREE_Y - 1, 0);
	private static final Pattern ACTOR_NAME = Pattern.compile("[A-Za-z0-9_]{1,16}");

	private final MinaConfig config;
	private final MinaSnapshotter snapshotter;
	private final MinaTurnController turnController;
	private final MinaActionExecutor actionExecutor;

	public MinaTestCommands(MinaConfig config, MinaSnapshotter snapshotter, MinaTurnController turnController, MinaActionExecutor actionExecutor) {
		this.config = config;
		this.snapshotter = snapshotter;
		this.turnController = turnController;
		this.actionExecutor = actionExecutor;
	}

	public void register() {
		if (!Boolean.getBoolean("mina.testHarness")) {
			return;
		}
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				literal("mina-test")
					.then(literal("setup")
						.then(literal("chop_tree").executes(context -> setupChopTree(context.getSource())))
						.then(literal("follow_player").executes(context -> setupFollowPlayer(context.getSource())))
						.then(literal("blocked_chop_tree").executes(context -> setupBlockedChopTree(context.getSource()))))
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
				.then(literal("actor")
					.then(literal("spawn")
						.then(argument("name", StringArgumentType.word())
							.executes(context -> actorSpawn(context.getSource(), StringArgumentType.getString(context, "name")))))
					.then(literal("leave")
						.then(argument("name", StringArgumentType.word())
							.executes(context -> actorLeave(context.getSource(), StringArgumentType.getString(context, "name")))))
					.then(literal("tp")
						.then(argument("name", StringArgumentType.word())
							.then(argument("position", StringArgumentType.greedyString())
								.executes(context -> actorTeleport(
									context.getSource(),
									StringArgumentType.getString(context, "name"),
									StringArgumentType.getString(context, "position")
								))))))
				.then(literal("world")
					.then(literal("mutate")
						.then(argument("operation", StringArgumentType.word())
							.executes(context -> worldMutate(context.getSource(), StringArgumentType.getString(context, "operation"))))))
				.then(literal("ready").executes(context -> ready(context.getSource())))
				.then(literal("deny_actions").executes(context -> denyActions(context.getSource())))
				.then(literal("allow_actions").executes(context -> allowActions(context.getSource())))
				.then(literal("leave_body").executes(context -> leaveBody(context.getSource())))
				.then(literal("move_requester_far").executes(context -> moveRequesterFar(context.getSource())))
				.then(literal("move_body_far").executes(context -> moveBodyFar(context.getSource())))
				.then(literal("remove_target_log").executes(context -> removeTargetLog(context.getSource())))
				.then(literal("snapshot").executes(context -> snapshot(context.getSource())))
				.then(literal("assert")
					.then(literal("chop_tree").executes(context -> assertChopTree(context.getSource())))
					.then(literal("follow_player").executes(context -> assertFollowPlayer(context.getSource())))
					.then(literal("target_log_present").executes(context -> assertTargetLogPresent(context.getSource())))
					.then(literal("upper_log_absent").executes(context -> assertUpperLogAbsent(context.getSource()))))
				.then(literal("stop").executes(context -> stop(context.getSource())))
		));
	}

	private int setupChopTree(CommandSourceStack source) {
		setupWorldAndPlayers(source);
		source.sendSuccess(() -> Component.literal("Mina test chop_tree setup complete. Poll /mina-test ready before requesting."), false);
		return 1;
	}

	private int setupFollowPlayer(CommandSourceStack source) {
		setupWorldAndPlayers(source);
		source.sendSuccess(() -> Component.literal("Mina test follow_player setup complete. Poll /mina-test ready before requesting."), false);
		return 1;
	}

	private int setupBlockedChopTree(CommandSourceStack source) {
		setupWorldAndPlayers(source);
		blockTreeApproaches(source.getLevel());
		source.sendSuccess(() -> Component.literal("Mina test blocked_chop_tree setup complete. Poll /mina-test ready before requesting."), false);
		return 1;
	}

	private int fixtureReset(CommandSourceStack source, String name) {
		return switch (name) {
			case "chop_tree" -> {
				setupWorldAndPlayers(source);
				source.sendSuccess(() -> Component.literal("Mina test fixture chop_tree reset complete. Poll /mina-test ready before requesting."), false);
				yield 1;
			}
			case "follow_player" -> {
				setupWorldAndPlayers(source);
				source.sendSuccess(() -> Component.literal("Mina test fixture follow_player reset complete. Poll /mina-test ready before requesting."), false);
				yield 1;
			}
			case "blocked_chop_tree" -> {
				setupWorldAndPlayers(source);
				blockTreeApproaches(source.getLevel());
				source.sendSuccess(() -> Component.literal("Mina test fixture blocked_chop_tree reset complete. Poll /mina-test ready before requesting."), false);
				yield 1;
			}
			default -> {
				source.sendFailure(Component.literal("Unknown Mina test fixture: " + name));
				yield 0;
			}
		};
	}

	private void setupWorldAndPlayers(CommandSourceStack source) {
		MinecraftServer server = source.getServer();
		prepareChopTreeWorld(source.getLevel());
		run(server, "difficulty peaceful");
		run(server, "kill @e[type=minecraft:creeper]");
		run(server, "time set day");
		run(server, "weather clear");
		run(server, "puppet " + TEST_PLAYER + " spawn");
		run(server, "puppet " + config.bodyUsername + " spawn");
		config.allow(TEST_PLAYER);
	}

	private int ready(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		MinecraftServer server = source.getServer();
		ServerPlayer requester = server.getPlayerList().getPlayer(TEST_PLAYER);
		ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
		boolean markerReady = level.getBlockState(SETUP_MARKER).is(Blocks.GRASS_BLOCK);
		boolean targetReady = level.getBlockState(TARGET_LOG).is(Blocks.SPRUCE_LOG);
		if (requester != null) {
			run(server, "tp " + TEST_PLAYER + " 0.5 " + TREE_Y + " -2.5 0 0");
			resetVitals(requester);
		}
		if (body != null) {
			run(server, "tp " + config.bodyUsername + " 0.5 " + TREE_Y + " -1.5 0 0");
		}
		if (!markerReady || !targetReady || requester == null || body == null) {
			source.sendFailure(Component.literal(
				"Mina test not ready: marker=" + markerReady
					+ ", target_log=" + targetReady
					+ ", requester_online=" + (requester != null)
					+ ", body_online=" + (body != null)
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

	private int leaveBody(CommandSourceStack source) {
		run(source.getServer(), "puppet " + config.bodyUsername + " leave");
		source.sendSuccess(() -> Component.literal("Mina test body left."), false);
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

	private int actorSpawn(CommandSourceStack source, String name) {
		if (!validActorName(source, name)) {
			return 0;
		}
		run(source.getServer(), "puppet " + name + " spawn");
		source.sendSuccess(() -> Component.literal("Mina test actor " + name + " spawned."), false);
		return 1;
	}

	private int actorLeave(CommandSourceStack source, String name) {
		if (!validActorName(source, name)) {
			return 0;
		}
		run(source.getServer(), "puppet " + name + " leave");
		source.sendSuccess(() -> Component.literal("Mina test actor " + name + " left."), false);
		return 1;
	}

	private int actorTeleport(CommandSourceStack source, String name, String position) {
		if (!validActorName(source, name)) {
			return 0;
		}
		String normalized = normalizedPosition(position);
		if (normalized.isBlank()) {
			source.sendFailure(Component.literal("Mina test actor tp requires: x y z [yaw pitch]."));
			return 0;
		}
		run(source.getServer(), "tp " + name + " " + normalized);
		source.sendSuccess(() -> Component.literal("Mina test actor " + name + " teleported."), false);
		return 1;
	}

	private int worldMutate(CommandSourceStack source, String operation) {
		return switch (operation) {
			case "remove_target_log" -> removeTargetLog(source);
			case "block_tree_approaches" -> {
				blockTreeApproaches(source.getLevel());
				source.sendSuccess(() -> Component.literal("Mina test world mutate block_tree_approaches complete."), false);
				yield 1;
			}
			case "move_requester_far" -> moveRequesterFar(source);
			case "move_body_far" -> moveBodyFar(source);
			case "deny_actions" -> denyActions(source);
			case "allow_actions" -> allowActions(source);
			case "leave_body" -> leaveBody(source);
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
			case "nearby_hostile" -> nearbyHostile(source);
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

	private int moveBodyFar(CommandSourceStack source) {
		ServerPlayer body = source.getServer().getPlayerList().getPlayer(config.bodyUsername);
		if (body == null) {
			source.sendFailure(Component.literal("Mina body is not online."));
			return 0;
		}
		run(source.getServer(), "tp " + config.bodyUsername + " -4.5 " + TREE_Y + " -4.5 0 0");
		source.sendSuccess(() -> Component.literal("Mina test body moved far."), false);
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
		requester.setHealth(4.0F);
		source.sendSuccess(() -> Component.literal("Mina test world mutate low_health complete."), false);
		return 1;
	}

	private int lowHunger(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online."));
			return 0;
		}
		requester.getFoodData().setFoodLevel(4);
		requester.getFoodData().setSaturation(0.0F);
		source.sendSuccess(() -> Component.literal("Mina test world mutate low_hunger complete."), false);
		return 1;
	}

	private int nearbyHostile(CommandSourceStack source) {
		run(source.getServer(), "difficulty normal");
		run(source.getServer(), "summon minecraft:creeper 1.5 " + TREE_Y + " -2.5 {NoAI:1b,Silent:1b,PersistenceRequired:1b}");
		source.sendSuccess(() -> Component.literal("Mina test world mutate nearby_hostile complete."), false);
		return 1;
	}

	private void resetVitals(ServerPlayer player) {
		player.setHealth(player.getMaxHealth());
		player.getFoodData().setFoodLevel(20);
		player.getFoodData().setSaturation(5.0F);
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

	private int assertChopTree(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		boolean markerReady = level.getBlockState(SETUP_MARKER).is(Blocks.GRASS_BLOCK);
		if (!markerReady) {
			source.sendFailure(Component.literal("Mina test chop_tree failed: setup marker is missing."));
			return 0;
		}
		boolean broken = level.getBlockState(TARGET_LOG).is(Blocks.AIR);
		if (!broken) {
			source.sendFailure(Component.literal("Mina test chop_tree failed: target log still exists."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test chop_tree passed."), false);
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

	private int assertUpperLogAbsent(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		boolean absent = level.getBlockState(UPPER_LOG).is(Blocks.AIR);
		if (!absent) {
			source.sendFailure(Component.literal("Mina test upper_log_absent failed: replacement log still exists."));
			return 0;
		}
		source.sendSuccess(() -> Component.literal("Mina test upper_log_absent passed."), false);
		return 1;
	}

	private int assertFollowPlayer(CommandSourceStack source) {
		ServerLevel level = source.getLevel();
		boolean markerReady = level.getBlockState(SETUP_MARKER).is(Blocks.GRASS_BLOCK);
		if (!markerReady) {
			source.sendFailure(Component.literal("Mina test follow_player failed: setup marker is missing."));
			return 0;
		}
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		ServerPlayer body = source.getServer().getPlayerList().getPlayer(config.bodyUsername);
		if (requester == null || body == null) {
			source.sendFailure(Component.literal("Mina test follow_player failed: requester/body offline."));
			return 0;
		}
		double distance = Math.sqrt(body.distanceToSqr(requester));
		if (distance > 4.0D) {
			source.sendFailure(Component.literal(String.format(java.util.Locale.ROOT, "Mina test follow_player failed: distance %.2f.", distance)));
			return 0;
		}
		source.sendSuccess(() -> Component.literal(String.format(java.util.Locale.ROOT, "Mina test follow_player passed: distance %.2f.", distance)), false);
		return 1;
	}

	private int stop(CommandSourceStack source) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		actionExecutor.stopBody(source.getServer(), requester, config);
		source.sendSuccess(() -> Component.literal("Mina test body stopped."), false);
		return 1;
	}

	private static void run(MinecraftServer server, String command) {
		server.getCommands().performPrefixedCommand(
			server.createCommandSourceStack().withMaximumPermission(PermissionSet.ALL_PERMISSIONS),
			command
		);
	}

	private static boolean validActorName(CommandSourceStack source, String name) {
		if (ACTOR_NAME.matcher(name).matches()) {
			return true;
		}
		source.sendFailure(Component.literal("Invalid Mina test actor name: " + name));
		return false;
	}

	private static String normalizedPosition(String position) {
		String[] parts = position.trim().split("\\s+");
		if (parts.length != 3 && parts.length != 5) {
			return "";
		}
		for (String part : parts) {
			try {
				Double.parseDouble(part);
			} catch (NumberFormatException exception) {
				return "";
			}
		}
		return String.join(" ", parts);
	}

	private static void prepareChopTreeWorld(ServerLevel level) {
		for (int chunkX = -1; chunkX <= 0; chunkX++) {
			for (int chunkZ = -1; chunkZ <= 0; chunkZ++) {
				level.setChunkForced(chunkX, chunkZ, true);
				level.getChunk(chunkX, chunkZ);
			}
		}
		for (int x = -5; x <= 5; x++) {
			for (int z = -5; z <= 5; z++) {
				level.setBlock(new BlockPos(x, TREE_Y - 1, z), Blocks.GRASS_BLOCK.defaultBlockState(), 3);
				for (int y = TREE_Y; y <= TREE_Y + 8; y++) {
					level.setBlock(new BlockPos(x, y, z), Blocks.AIR.defaultBlockState(), 3);
				}
			}
		}
		level.setBlock(TARGET_LOG, Blocks.SPRUCE_LOG.defaultBlockState(), 3);
		level.setBlock(UPPER_LOG, Blocks.SPRUCE_LOG.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X + 1, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X - 1, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z + 1), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z - 1), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
	}

	private static void blockTreeApproaches(ServerLevel level) {
		BlockPos[] logs = {TARGET_LOG, UPPER_LOG};
		for (BlockPos log : logs) {
			level.setBlock(log.north(), Blocks.COBBLESTONE.defaultBlockState(), 3);
			level.setBlock(log.south(), Blocks.COBBLESTONE.defaultBlockState(), 3);
			level.setBlock(log.east(), Blocks.COBBLESTONE.defaultBlockState(), 3);
			level.setBlock(log.west(), Blocks.COBBLESTONE.defaultBlockState(), 3);
		}
	}
}
