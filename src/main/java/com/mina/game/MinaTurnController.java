package com.mina.game;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import com.mina.net.SidecarClient;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;

public final class MinaTurnController {
	private final MinaConfig config;
	private final SidecarClient sidecarClient;
	private final MinaSnapshotter snapshotter;
	private final MinaActionExecutor actionExecutor;
	private final Map<UUID, CompletableFuture<JsonObject>> activeTurns = new ConcurrentHashMap<>();

	public MinaTurnController(
		MinaConfig config,
		SidecarClient sidecarClient,
		MinaSnapshotter snapshotter,
		MinaActionExecutor actionExecutor
	) {
		this.config = config;
		this.sidecarClient = sidecarClient;
		this.snapshotter = snapshotter;
		this.actionExecutor = actionExecutor;
	}

	public int submitPlayerTurn(MinecraftServer server, ServerPlayer player, String trigger, String content, boolean thinkingMessage) {
		return submitPlayerTurn(server, player, trigger, content, thinkingMessage, UUID.randomUUID().toString());
	}

	public int submitPlayerTurn(MinecraftServer server, ServerPlayer player, String trigger, String content, boolean thinkingMessage, String requestId) {
		if (player == null) {
			return 0;
		}
		if (!config.enabled) {
			player.sendSystemMessage(Component.literal("Mina is disabled in config/mina.json."));
			return 0;
		}

		UUID playerId = player.getUUID();
		CompletableFuture<JsonObject> previous = activeTurns.remove(playerId);
		if (previous != null) {
			previous.cancel(true);
		}

		String resolvedRequestId = requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
		JsonObject payload = snapshotter.createTurnPayload(server, player, config, trigger, content, resolvedRequestId);
		MinaMod.LOGGER.info("mina turn start requestId={} player={} content={}", resolvedRequestId, player.getGameProfile().name(), content);
		if (thinkingMessage) {
			player.sendSystemMessage(Component.literal("[Mina] thinking..."));
		}
		CompletableFuture<JsonObject> future = sidecarClient.turn(config, payload);
		activeTurns.put(playerId, future);
		future.whenComplete((response, throwable) -> {
			activeTurns.remove(playerId, future);
			server.executeIfPossible(() -> {
				if (throwable != null) {
					if (isCancellation(throwable)) {
						MinaMod.LOGGER.info("Mina sidecar turn cancelled requestId={} player={}", resolvedRequestId, player.getGameProfile().name());
						return;
					}
					MinaMod.LOGGER.warn("Mina sidecar turn failed", throwable);
					player.sendSystemMessage(Component.literal("[Mina] sidecar request failed: " + rootMessage(throwable)));
					return;
				}
				MinaMod.LOGGER.info("mina turn response requestId={} response={}", resolvedRequestId, response);
				processSidecarResponse(server, player, resolvedRequestId, response);
			});
		});
		return 1;
	}

	public void processSidecarResponse(MinecraftServer server, ServerPlayer requester, String requestId, JsonObject response) {
		if (response == null) {
			return;
		}
		JsonArray results = actionExecutor.executeResponse(server, requester, config, response);
		if (results.size() > 0) {
			reportActionResults(server, requester, requestId, results);
		}
	}

	public void reportActionResults(MinecraftServer server, ServerPlayer requester, String requestId, JsonArray actionResults) {
		if (actionResults == null || actionResults.size() == 0) {
			return;
		}
		JsonObject payload = new JsonObject();
		payload.addProperty("request_id", requestId == null ? "" : requestId);
		payload.add("action_results", actionResults);
		if (requester != null) {
			payload.add("snapshot", snapshotter.snapshot(server, requester, config));
		}
		sidecarClient.actionResults(config, payload).whenComplete((response, throwable) -> server.executeIfPossible(() -> {
			if (throwable != null) {
				MinaMod.LOGGER.warn("Mina sidecar action-results failed", throwable);
				return;
			}
			if (hasMessagesOrActions(response)) {
				MinaMod.LOGGER.info("mina action-results response requestId={} response={}", requestId, response);
				processSidecarResponse(server, requester, requestId, response);
			}
		}));
	}

	private static boolean hasMessagesOrActions(JsonObject response) {
		if (response == null) {
			return false;
		}
		JsonArray messages = response.getAsJsonArray("messages");
		JsonArray actions = response.getAsJsonArray("actions");
		return messages != null && messages.size() > 0 || actions != null && actions.size() > 0;
	}

	private static boolean isCancellation(Throwable throwable) {
		Throwable current = throwable;
		while (current != null) {
			if (current instanceof CancellationException) {
				return true;
			}
			current = current.getCause();
		}
		return false;
	}

	private static String rootMessage(Throwable throwable) {
		Throwable current = throwable;
		while (current.getCause() != null) {
			current = current.getCause();
		}
		return current.getMessage() == null ? current.getClass().getSimpleName() : current.getMessage();
	}
}
