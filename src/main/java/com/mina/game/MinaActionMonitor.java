package com.mina.game;

import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.block.state.BlockState;

import java.util.Iterator;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;

public final class MinaActionMonitor {
	private final MinaConfig config;
	private final CopyOnWriteArrayList<ActiveMonitor> active = new CopyOnWriteArrayList<>();
	private MinaTurnController controller;
	private int ticks;

	public MinaActionMonitor(MinaConfig config) {
		this.config = config;
	}

	public void setController(MinaTurnController controller) {
		this.controller = controller;
	}

	public void track(MinecraftServer server, ServerPlayer requester, String requestId, JsonObject action) {
		JsonObject monitor = action.getAsJsonObject("monitor");
		int deadlineTicks = intValue(monitor, "deadline_ticks", intValue(action, "deadline_ticks", 100));
		ActiveMonitor activeMonitor = new ActiveMonitor(
			requestId == null ? "" : requestId,
			requester == null ? null : requester.getUUID(),
			action.deepCopy(),
			monitor.deepCopy(),
			ticks,
			Math.max(1, deadlineTicks)
		);
		active.add(activeMonitor);
		MinaMod.LOGGER.info(
			"mina monitor start actionId={} taskId={} stepId={} type={} deadlineTicks={}",
			string(action, "id"),
			string(action, "task_id"),
			string(action, "step_id"),
			string(monitor, "type"),
			activeMonitor.deadlineTicks
		);
	}

	public void onEndServerTick(MinecraftServer server) {
		ticks++;
		if (controller == null || active.isEmpty()) {
			return;
		}
		Iterator<ActiveMonitor> iterator = active.iterator();
		while (iterator.hasNext()) {
			ActiveMonitor monitor = iterator.next();
			ServerPlayer requester = monitor.requesterId == null ? null : server.getPlayerList().getPlayer(monitor.requesterId);
			JsonObject result = check(server, requester, monitor);
			if (result == null) {
				continue;
			}
			active.remove(monitor);
			MinaMod.LOGGER.info(
				"mina monitor result actionId={} taskId={} stepId={} result={}",
				string(monitor.action, "id"),
				string(monitor.action, "task_id"),
				string(monitor.action, "step_id"),
				result
			);
			controller.reportMonitorResult(server, requester, monitor.requestId, monitor.action, result);
		}
		if (ticks % 40 == 0) {
			for (ActiveMonitor monitor : active) {
				ServerPlayer requester = monitor.requesterId == null ? null : server.getPlayerList().getPlayer(monitor.requesterId);
				controller.reportObservation(server, requester, monitor.requestId, string(monitor.action, "task_id"));
			}
		}
	}

	private JsonObject check(MinecraftServer server, ServerPlayer requester, ActiveMonitor activeMonitor) {
		JsonObject monitor = activeMonitor.monitor;
		String type = string(monitor, "type");
		JsonObject success = null;
		if ("body_online".equals(type)) {
			ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
			if (body != null) {
				success = result("success", "body is online");
			}
		} else if ("body_near".equals(type)) {
			ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
			if (body != null) {
				double x = doubleValue(monitor, "x", body.getX());
				double y = doubleValue(monitor, "y", body.getY());
				double z = doubleValue(monitor, "z", body.getZ());
				double radius = doubleValue(monitor, "radius", 2.0D);
				double distance = Math.sqrt(body.distanceToSqr(x, y, z));
				if (distance <= radius) {
					success = result("success", "body reached target");
					success.addProperty("distance", round(distance));
				}
			}
		} else if ("block_absent".equals(type)) {
			ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
			ServerLevel level = body != null ? body.level() : requester == null ? null : requester.level();
			if (level != null) {
				BlockPos pos = new BlockPos(intValue(monitor, "x", 0), intValue(monitor, "y", 0), intValue(monitor, "z", 0));
				BlockState state = level.getBlockState(pos);
				String actual = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
				String expected = string(monitor, "block");
				if (state.isAir() || (!expected.isBlank() && !expected.equals(actual))) {
					success = result("success", "target block is absent");
					success.addProperty("actual_block", actual);
				}
			}
		}
		if (success != null) {
			return success;
		}
		if (ticks - activeMonitor.startedTick >= activeMonitor.deadlineTicks) {
			JsonObject timeout = result("timeout", "monitor deadline reached");
			timeout.addProperty("elapsed_ticks", ticks - activeMonitor.startedTick);
			return timeout;
		}
		return null;
	}

	private static JsonObject result(String status, String reason) {
		JsonObject json = new JsonObject();
		json.addProperty("status", status);
		json.addProperty("reason", reason);
		return json;
	}

	private static String string(JsonObject object, String key) {
		if (object == null || !object.has(key) || object.get(key).isJsonNull()) {
			return "";
		}
		return object.get(key).getAsString();
	}

	private static int intValue(JsonObject object, String key, int fallback) {
		if (object == null || !object.has(key) || object.get(key).isJsonNull()) {
			return fallback;
		}
		return object.get(key).getAsInt();
	}

	private static double doubleValue(JsonObject object, String key, double fallback) {
		if (object == null || !object.has(key) || object.get(key).isJsonNull()) {
			return fallback;
		}
		return object.get(key).getAsDouble();
	}

	private static double round(double value) {
		return Math.round(value * 100.0D) / 100.0D;
	}

	private record ActiveMonitor(
		String requestId,
		UUID requesterId,
		JsonObject action,
		JsonObject monitor,
		int startedTick,
		int deadlineTicks
	) {
	}
}
