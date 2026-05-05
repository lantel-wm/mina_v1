package com.mina.game;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import com.mina.net.SidecarClient;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

public final class MinaTurnController {
	private final MinaConfig config;
	private final SidecarClient sidecarClient;
	private final MinaSnapshotter snapshotter;
	private final MinaActionExecutor actionExecutor;
	private final Map<UUID, CompletableFuture<JsonObject>> activeTurns = new ConcurrentHashMap<>();
	private final Map<String, Integer> progressSequences = new ConcurrentHashMap<>();

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
			MinaChat.sendError(player, "Mina is disabled in config/mina.json.");
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
			sendPlayerRequestEcho(player, trigger, content);
			MinaChat.sendThinking(player);
		}
		CompletableFuture<JsonObject> future = sidecarClient.turn(config, payload);
		activeTurns.put(playerId, future);
		if (thinkingMessage) {
			pollProgress(server, player, resolvedRequestId, future);
		}
		future.whenComplete((response, throwable) -> {
			activeTurns.remove(playerId, future);
			server.executeIfPossible(() -> {
				if (throwable != null) {
					if (isCancellation(throwable)) {
						MinaMod.LOGGER.info("Mina sidecar turn cancelled requestId={} player={}", resolvedRequestId, player.getGameProfile().name());
						return;
					}
					MinaMod.LOGGER.warn("Mina sidecar turn failed", throwable);
					MinaChat.sendError(player, "sidecar request failed: " + rootMessage(throwable));
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
		sendProgressEvents(requester, requestId, response.getAsJsonArray("progress_events"));
		scheduleProgressCleanup(requestId);
		JsonArray results = actionExecutor.executeResponse(server, requester, config, response);
		if (results.size() > 0) {
			reportActionResults(server, requester, requestId, results);
		}
	}

	private void pollProgress(MinecraftServer server, ServerPlayer player, String requestId, CompletableFuture<JsonObject> turnFuture) {
		CompletableFuture.runAsync(() -> {
			while (!turnFuture.isDone()) {
				try {
					TimeUnit.MILLISECONDS.sleep(750);
					if (turnFuture.isDone()) {
						return;
					}
					int after = progressSequences.getOrDefault(requestId, 0);
					JsonObject response = sidecarClient.progress(config, requestId, after).get(3, TimeUnit.SECONDS);
					JsonArray events = response.getAsJsonArray("events");
					if (events != null && events.size() > 0) {
						server.executeIfPossible(() -> sendProgressEvents(player, requestId, events));
					}
				} catch (InterruptedException exception) {
					Thread.currentThread().interrupt();
					return;
				} catch (Exception exception) {
					MinaMod.LOGGER.debug("Mina progress polling failed requestId={}", requestId, exception);
				}
			}
		});
	}

	private void scheduleProgressCleanup(String requestId) {
		CompletableFuture.delayedExecutor(30, TimeUnit.SECONDS).execute(() -> progressSequences.remove(requestId));
	}

	private void sendProgressEvents(ServerPlayer player, String requestId, JsonArray events) {
		if (player == null || events == null) {
			return;
		}
		int after = progressSequences.getOrDefault(requestId, 0);
		for (JsonElement element : events) {
			if (!element.isJsonObject()) {
				continue;
			}
			JsonObject event = element.getAsJsonObject();
			int seq = event.has("seq") ? event.get("seq").getAsInt() : 0;
			if (seq <= after) {
				continue;
			}
			String message = event.has("message") && !event.get("message").isJsonNull()
				? event.get("message").getAsString()
				: "";
			if (!message.isBlank()) {
				MinaChat.sendProgress(player, message);
			}
			after = Math.max(after, seq);
		}
		progressSequences.put(requestId, after);
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

	private static void sendPlayerRequestEcho(ServerPlayer player, String trigger, String content) {
		if (!"command".equals(trigger)) {
			return;
		}
		MinaChat.sendPlayerEcho(player, content);
	}

	private static String rootMessage(Throwable throwable) {
		Throwable current = throwable;
		while (current.getCause() != null) {
			current = current.getCause();
		}
		return current.getMessage() == null ? current.getClass().getSimpleName() : current.getMessage();
	}
}
