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

import static net.minecraft.commands.Commands.argument;
import static net.minecraft.commands.Commands.literal;

public final class MinaTestCommands {
	private static final Gson GSON = new Gson();
	private static final String TEST_PLAYER = "mina_tester";
	private static final int TREE_X = 2;
	private static final int TREE_Y = 80;
	private static final int TREE_Z = 0;
	private static final BlockPos TARGET_LOG = new BlockPos(TREE_X, TREE_Y, TREE_Z);
	private static final BlockPos SETUP_MARKER = new BlockPos(0, TREE_Y - 1, 0);

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
					.then(literal("chop_tree").executes(context -> setupChopTree(context.getSource()))))
				.then(literal("request")
					.then(argument("content", StringArgumentType.greedyString())
						.executes(context -> request(context.getSource(), StringArgumentType.getString(context, "content")))))
				.then(literal("ready").executes(context -> ready(context.getSource())))
				.then(literal("snapshot").executes(context -> snapshot(context.getSource())))
				.then(literal("assert")
					.then(literal("chop_tree").executes(context -> assertChopTree(context.getSource()))))
				.then(literal("stop").executes(context -> stop(context.getSource())))
		));
	}

	private int setupChopTree(CommandSourceStack source) {
		MinecraftServer server = source.getServer();
		prepareChopTreeWorld(source.getLevel());
		run(server, "time set day");
		run(server, "weather clear");
		run(server, "puppet " + TEST_PLAYER + " spawn");
		run(server, "puppet " + config.bodyUsername + " spawn");
		config.allow(TEST_PLAYER);
		source.sendSuccess(() -> Component.literal("Mina test chop_tree setup complete. Poll /mina-test ready before requesting."), false);
		return 1;
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

	private int request(CommandSourceStack source, String content) {
		ServerPlayer requester = source.getServer().getPlayerList().getPlayer(TEST_PLAYER);
		if (requester == null) {
			source.sendFailure(Component.literal("Test requester is not online. Run /mina-test setup chop_tree first."));
			return 0;
		}
		return turnController.submitPlayerTurn(source.getServer(), requester, "command", content, false);
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
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 1, TREE_Z), Blocks.SPRUCE_LOG.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X + 1, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X - 1, TREE_Y + 2, TREE_Z), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z + 1), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
		level.setBlock(new BlockPos(TREE_X, TREE_Y + 2, TREE_Z - 1), Blocks.SPRUCE_LEAVES.defaultBlockState(), 3);
	}
}
