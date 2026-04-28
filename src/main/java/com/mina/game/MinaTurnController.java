package com.mina.game;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import com.mina.net.SidecarClient;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;

public final class MinaTurnController {
	private final MinaConfig config;
	private final SidecarClient sidecarClient;
	private final MinaSnapshotter snapshotter;
	private final MinaActionExecutor actionExecutor;
	private final MinaActionMonitor actionMonitor;
	private final Map<UUID, CompletableFuture<JsonObject>> activeTurns = new ConcurrentHashMap<>();

	public MinaTurnController(
		MinaConfig config,
		SidecarClient sidecarClient,
		MinaSnapshotter snapshotter,
		MinaActionExecutor actionExecutor,
		MinaActionMonitor actionMonitor
	) {
		this.config = config;
		this.sidecarClient = sidecarClient;
		this.snapshotter = snapshotter;
		this.actionExecutor = actionExecutor;
		this.actionMonitor = actionMonitor;
	}

	public int submitPlayerTurn(MinecraftServer server, ServerPlayer player, String trigger, String content, boolean thinkingMessage) {
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

		String requestId = UUID.randomUUID().toString();
		JsonObject payload = snapshotter.createTurnPayload(server, player, config, trigger, content, requestId);
		MinaMod.LOGGER.info("mina turn start requestId={} player={} content={}", requestId, player.getGameProfile().name(), content);
		if (thinkingMessage) {
			player.sendSystemMessage(Component.literal("[Mina] thinking..."));
		}
		CompletableFuture<JsonObject> future = sidecarClient.turn(config, payload);
		activeTurns.put(playerId, future);
		future.whenComplete((response, throwable) -> {
			activeTurns.remove(playerId, future);
			server.executeIfPossible(() -> {
				if (throwable != null) {
					MinaMod.LOGGER.warn("Mina sidecar turn failed", throwable);
					player.sendSystemMessage(Component.literal("[Mina] sidecar request failed: " + rootMessage(throwable)));
					return;
				}
				MinaMod.LOGGER.info("mina turn response requestId={} response={}", requestId, response);
				processSidecarResponse(server, player, requestId, response);
			});
		});
		return 1;
	}

	public void processSidecarResponse(MinecraftServer server, ServerPlayer requester, String requestId, JsonObject response) {
		if (response == null) {
			return;
		}
		JsonArray actions = response.getAsJsonArray("actions");
		JsonArray results = actionExecutor.executeResponse(server, requester, config, response);
		cancelMonitorsForSuccessfulStops(actions, results);
		registerMonitors(server, requester, requestId, actions, results);
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

	public void reportMonitorResult(MinecraftServer server, ServerPlayer requester, String requestId, JsonObject action, JsonObject monitorResult) {
		JsonObject result = new JsonObject();
		result.addProperty("action_id", string(action, "id"));
		result.addProperty("task_id", string(action, "task_id"));
		result.addProperty("step_id", string(action, "step_id"));
		result.addProperty("name", string(action, "name"));
		result.addProperty("status", string(monitorResult, "status"));
		result.addProperty("command_success", true);
		result.add("monitor_result", monitorResult);
		if (requester != null) {
			result.add("snapshot", snapshotter.snapshot(server, requester, config));
		}
		JsonArray results = new JsonArray();
		results.add(result);
		reportActionResults(server, requester, requestId, results);
	}

	public void reportObservation(MinecraftServer server, ServerPlayer requester, String requestId, String taskId) {
		if (requester == null) {
			return;
		}
		JsonObject payload = new JsonObject();
		payload.addProperty("request_id", requestId == null ? "" : requestId);
		payload.addProperty("task_id", taskId == null ? "" : taskId);
		payload.add("snapshot", snapshotter.snapshot(server, requester, config));
		sidecarClient.observations(config, payload).whenComplete((response, throwable) -> server.executeIfPossible(() -> {
			if (throwable != null) {
				MinaMod.LOGGER.debug("Mina sidecar observation failed", throwable);
				return;
			}
			if (hasMessagesOrActions(response)) {
				MinaMod.LOGGER.info("mina observation response requestId={} response={}", requestId, response);
				processSidecarResponse(server, requester, requestId, response);
			}
		}));
	}

	private void registerMonitors(MinecraftServer server, ServerPlayer requester, String requestId, JsonArray actions, JsonArray results) {
		if (actions == null || results == null) {
			return;
		}
		int limit = Math.min(actions.size(), results.size());
		for (int index = 0; index < limit; index++) {
			JsonElement actionElement = actions.get(index);
			JsonElement resultElement = results.get(index);
			if (!actionElement.isJsonObject() || !resultElement.isJsonObject()) {
				continue;
			}
			JsonObject action = actionElement.getAsJsonObject();
			JsonObject result = resultElement.getAsJsonObject();
			if ("monitor_pending".equals(string(result, "status")) && action.has("monitor") && action.get("monitor").isJsonObject()) {
				actionMonitor.track(server, requester, requestId, action);
			}
		}
	}

	private void cancelMonitorsForSuccessfulStops(JsonArray actions, JsonArray results) {
		if (actions == null || results == null) {
			return;
		}
		int limit = Math.min(actions.size(), results.size());
		for (int index = 0; index < limit; index++) {
			JsonElement actionElement = actions.get(index);
			JsonElement resultElement = results.get(index);
			if (!actionElement.isJsonObject() || !resultElement.isJsonObject()) {
				continue;
			}
			JsonObject action = actionElement.getAsJsonObject();
			JsonObject result = resultElement.getAsJsonObject();
			if ("body_stop".equals(string(action, "name")) && bool(result, "command_success", false)) {
				actionMonitor.cancelTask(string(action, "task_id"), string(action, "step_id"));
			}
		}
	}

	private static boolean hasMessagesOrActions(JsonObject response) {
		if (response == null) {
			return false;
		}
		JsonArray messages = response.getAsJsonArray("messages");
		JsonArray actions = response.getAsJsonArray("actions");
		return messages != null && messages.size() > 0 || actions != null && actions.size() > 0;
	}

	private static String string(JsonObject object, String key) {
		if (object == null || !object.has(key) || object.get(key).isJsonNull()) {
			return "";
		}
		return object.get(key).getAsString();
	}

	private static boolean bool(JsonObject object, String key, boolean fallback) {
		if (object == null || !object.has(key) || object.get(key).isJsonNull()) {
			return fallback;
		}
		return object.get(key).getAsBoolean();
	}

	private static String rootMessage(Throwable throwable) {
		Throwable current = throwable;
		while (current.getCause() != null) {
			current = current.getCause();
		}
		return current.getMessage() == null ? current.getClass().getSimpleName() : current.getMessage();
	}
}
