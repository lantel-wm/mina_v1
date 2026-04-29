package com.mina.game;

import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import com.mina.net.SidecarClient;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public final class MinaCompanionTicker {
	private final MinaConfig config;
	private final SidecarClient sidecarClient;
	private final MinaSnapshotter snapshotter;
	private final MinaActionExecutor actionExecutor;
	private final Set<UUID> inFlight = ConcurrentHashMap.newKeySet();
	private int ticks;

	public MinaCompanionTicker(MinaConfig config, SidecarClient sidecarClient, MinaSnapshotter snapshotter, MinaActionExecutor actionExecutor) {
		this.config = config;
		this.sidecarClient = sidecarClient;
		this.snapshotter = snapshotter;
		this.actionExecutor = actionExecutor;
	}

	public void onEndServerTick(MinecraftServer server) {
		if (!config.enabled || !config.enableCompanion) {
			return;
		}
		ticks++;
		if (ticks % config.snapshotIntervalTicks != 0) {
			return;
		}
		for (ServerPlayer player : server.getPlayerList().getPlayers()) {
			UUID uuid = player.getUUID();
			if (!inFlight.add(uuid)) {
				continue;
			}
			String requestId = UUID.randomUUID().toString();
			JsonObject payload = snapshotter.createTurnPayload(server, player, config, "companion_tick", "", requestId);
			MinaMod.LOGGER.debug("mina companion turn start requestId={} player={}", requestId, player.getGameProfile().name());
			sidecarClient.turn(config, payload).whenComplete((response, throwable) -> {
				inFlight.remove(uuid);
				server.executeIfPossible(() -> {
					if (throwable != null) {
						MinaMod.LOGGER.debug("Mina companion tick failed", throwable);
						return;
					}
					if (response.has("messages") || response.has("actions")) {
						MinaMod.LOGGER.info("mina companion response requestId={} response={}", requestId, response);
					}
					actionExecutor.executeResponse(server, player, config, response);
				});
			});
		}
	}
}
