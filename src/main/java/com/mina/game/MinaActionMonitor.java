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
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;

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

	public int cancelTask(String taskId, String reason) {
		if (taskId == null || taskId.isBlank()) {
			return 0;
		}
		int cancelled = 0;
		for (ActiveMonitor monitor : active) {
			if (taskId.equals(string(monitor.action, "task_id"))) {
				active.remove(monitor);
				cancelled++;
			}
		}
		if (cancelled > 0) {
			MinaMod.LOGGER.info("mina monitor cancelled taskId={} count={} reason={}", taskId, cancelled, reason);
		}
		return cancelled;
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
		} else if ("body_targeted_block".equals(type)) {
			ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
			if (body != null) {
				BlockPos expectedPos = new BlockPos(intValue(monitor, "x", 0), intValue(monitor, "y", 0), intValue(monitor, "z", 0));
				HitResult hit = body.pick(5.0D, 0.0F, false);
				if (hit instanceof BlockHitResult blockHit && hit.getType() == HitResult.Type.BLOCK) {
					BlockPos actualPos = blockHit.getBlockPos();
					BlockState state = body.level().getBlockState(actualPos);
					String actualBlock = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
					String expectedBlock = string(monitor, "block");
					if (actualPos.equals(expectedPos) && (expectedBlock.isBlank() || expectedBlock.equals(actualBlock))) {
						success = result("success", "body targeted expected block");
						success.addProperty("actual_block", actualBlock);
					} else if (booleanValue(monitor, "allow_same_column", false)
						&& actualPos.getX() == expectedPos.getX()
						&& actualPos.getZ() == expectedPos.getZ()
						&& !expectedBlock.isBlank()
						&& expectedBlock.equals(actualBlock)) {
						success = result("retarget", "body targeted related block");
						success.addProperty("actual_x", actualPos.getX());
						success.addProperty("actual_y", actualPos.getY());
						success.addProperty("actual_z", actualPos.getZ());
						success.addProperty("actual_block", actualBlock);
					}
				}
			}
		} else if ("follow_requester".equals(type)) {
			ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
			if (body != null && requester != null) {
				double distance = Math.sqrt(body.distanceToSqr(requester));
				int elapsed = ticks - activeMonitor.startedTick;
				double maxDistance = doubleValue(monitor, "max_distance", 4.0D);
				int graceTicks = intValue(monitor, "grace_ticks", 80);
				if (elapsed >= graceTicks && distance > maxDistance) {
					success = result("reposition", "body drifted from requester");
					success.addProperty("distance", round(distance));
					success.addProperty("max_distance", maxDistance);
				} else if (elapsed >= activeMonitor.deadlineTicks) {
					success = result("success", "follow heartbeat");
					success.addProperty("distance", round(distance));
					success.addProperty("max_distance", maxDistance);
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

	private static boolean booleanValue(JsonObject object, String key, boolean fallback) {
		if (object == null || !object.has(key) || object.get(key).isJsonNull()) {
			return fallback;
		}
		return object.get(key).getAsBoolean();
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
