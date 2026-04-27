package com.mina.game;

import com.google.gson.JsonObject;
import com.mina.config.MinaConfig;
import com.mina.net.SidecarClient;
import com.mojang.brigadier.arguments.StringArgumentType;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import static net.minecraft.commands.Commands.argument;
import static net.minecraft.commands.Commands.literal;

public final class MinaCommands {
	private final MinaConfig config;
	private final SidecarClient sidecarClient;
	private final MinaActionExecutor actionExecutor;
	private final MinaTurnController turnController;

	public MinaCommands(MinaConfig config, SidecarClient sidecarClient, MinaActionExecutor actionExecutor, MinaTurnController turnController) {
		this.config = config;
		this.sidecarClient = sidecarClient;
		this.actionExecutor = actionExecutor;
		this.turnController = turnController;
	}

	public void register() {
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
			literal("mina")
				.then(argument("content", StringArgumentType.greedyString())
					.executes(context -> executeMina(context.getSource(), StringArgumentType.getString(context, "content"))))
		));

		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
			literal("mina-admin")
				.requires(this::isOperator)
				.then(literal("status").executes(context -> status(context.getSource())))
				.then(literal("reload").executes(context -> reload(context.getSource())))
				.then(literal("stop").executes(context -> stop(context.getSource())))
				.then(literal("allow")
					.then(argument("player", StringArgumentType.word())
						.executes(context -> allow(context.getSource(), StringArgumentType.getString(context, "player")))))
				.then(literal("deny")
					.then(argument("player", StringArgumentType.word())
						.executes(context -> deny(context.getSource(), StringArgumentType.getString(context, "player")))))
		));
	}

	private int executeMina(CommandSourceStack source, String content) {
		ServerPlayer player = source.getPlayer();
		if (player == null) {
			source.sendFailure(Component.literal("Mina can only be used by a player in v1."));
			return 0;
		}
		if (!config.enabled) {
			source.sendFailure(Component.literal("Mina is disabled in config/mina.json."));
			return 0;
		}

			return turnController.submitPlayerTurn(source.getServer(), player, "command", content, true);
	}

	private int status(CommandSourceStack source) {
		ServerPlayer requester = source.getPlayer();
		source.sendSuccess(() -> Component.literal("Mina body available: " + actionExecutor.isBodyAvailable(config)), false);
		sidecarClient.health(config).whenComplete((response, throwable) -> source.getServer().executeIfPossible(() -> {
			if (throwable != null) {
				source.sendFailure(Component.literal("Mina sidecar unhealthy: " + rootMessage(throwable)));
				return;
			}
			String model = response.has("model") ? response.get("model").getAsString() : "unknown";
			boolean configured = response.has("deepseek_configured") && response.get("deepseek_configured").getAsBoolean();
			source.sendSuccess(() -> Component.literal("Mina sidecar ok. model=" + model + ", deepseek_configured=" + configured), false);
		}));
		return 1;
	}

	private int reload(CommandSourceStack source) {
		config.reload();
		source.sendSuccess(() -> Component.literal("Reloaded Mina config."), false);
		return 1;
	}

	private int stop(CommandSourceStack source) {
		ServerPlayer requester = source.getPlayer();
		if (!config.canUseActions(source.getServer(), requester)) {
			source.sendFailure(Component.literal("You are not allowed to control Mina actions."));
			return 0;
		}
		actionExecutor.stopBody(source.getServer(), requester, config);
		source.sendSuccess(() -> Component.literal("Stopped Mina body actions."), false);
		return 1;
	}

	private int allow(CommandSourceStack source, String player) {
		config.allow(player);
		source.sendSuccess(() -> Component.literal("Allowed Mina actions for " + player), false);
		return 1;
	}

	private int deny(CommandSourceStack source, String player) {
		config.deny(player);
		source.sendSuccess(() -> Component.literal("Removed Mina action allowlist entry " + player), false);
		return 1;
	}

	private boolean isOperator(CommandSourceStack source) {
		ServerPlayer player = source.getPlayer();
		return player != null && source.getServer().getPlayerList().isOp(player.nameAndId());
	}
	static String rootMessage(Throwable throwable) {
		Throwable current = throwable;
		while (current.getCause() != null) {
			current = current.getCause();
		}
		return current.getMessage() == null ? current.getClass().getSimpleName() : current.getMessage();
	}
}
