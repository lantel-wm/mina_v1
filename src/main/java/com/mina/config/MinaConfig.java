package com.mina.config;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.mina.MinaMod;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class MinaConfig {
	private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
	private static final String CONFIG_FILE = "mina.json";

	public String sidecarBaseUrl = "http://127.0.0.1:18911";
	public long sidecarTimeoutMs = 60000;
	public boolean enabled = true;
	public boolean enableCompanion = false;
	public boolean allowedOperatorsOnlyForActions = true;
	public List<String> actionAllowlist = new ArrayList<>();
	public String bodyUsername = "mina";
	public boolean enableBody = true;
	public int snapshotIntervalTicks = 200;
	public int companionCooldownSeconds = 300;
	public int nearbyEntityRadius = 64;
	public int maxInventorySlotsReported = 46;
	public int maxNearbyEntitiesReported = 80;
	public List<String> dangerousCommandDenylist = new ArrayList<>(List.of(
		"op",
		"deop",
		"stop",
		"ban",
		"ban-ip",
		"pardon",
		"pardon-ip",
		"whitelist",
		"save-all",
		"save-off",
		"save-on"
	));

	private transient Path path;

	public static MinaConfig load() {
		Path path = FabricLoader.getInstance().getConfigDir().resolve(CONFIG_FILE);
		MinaConfig config = null;
		if (Files.exists(path)) {
			try (Reader reader = Files.newBufferedReader(path)) {
				config = GSON.fromJson(reader, MinaConfig.class);
			} catch (IOException | RuntimeException exception) {
				MinaMod.LOGGER.warn("Failed to read {}, using defaults", path, exception);
			}
		}
		if (config == null) {
			config = new MinaConfig();
		}
		config.path = path;
		config.normalize();
		if (!Files.exists(path)) {
			config.save();
		}
		return config;
	}

	public void reload() {
		MinaConfig loaded = load();
		this.sidecarBaseUrl = loaded.sidecarBaseUrl;
		this.sidecarTimeoutMs = loaded.sidecarTimeoutMs;
		this.enabled = loaded.enabled;
		this.enableCompanion = loaded.enableCompanion;
		this.allowedOperatorsOnlyForActions = loaded.allowedOperatorsOnlyForActions;
		this.actionAllowlist = loaded.actionAllowlist;
		this.bodyUsername = loaded.bodyUsername;
		this.enableBody = loaded.enableBody;
		this.snapshotIntervalTicks = loaded.snapshotIntervalTicks;
		this.companionCooldownSeconds = loaded.companionCooldownSeconds;
		this.nearbyEntityRadius = loaded.nearbyEntityRadius;
		this.maxInventorySlotsReported = loaded.maxInventorySlotsReported;
		this.maxNearbyEntitiesReported = loaded.maxNearbyEntitiesReported;
		this.dangerousCommandDenylist = loaded.dangerousCommandDenylist;
		this.path = loaded.path;
		normalize();
	}

	public void save() {
		try {
			Files.createDirectories(path.getParent());
			try (Writer writer = Files.newBufferedWriter(path)) {
				GSON.toJson(this, writer);
			}
		} catch (IOException exception) {
			MinaMod.LOGGER.warn("Failed to save {}", path, exception);
		}
	}

	public boolean canUseActions(MinecraftServer server, ServerPlayer player) {
		if (player == null) {
			return false;
		}
		if (!allowedOperatorsOnlyForActions) {
			return true;
		}
		String uuid = player.getUUID().toString().toLowerCase(Locale.ROOT);
		String name = player.getGameProfile().name().toLowerCase(Locale.ROOT);
		for (String allowed : actionAllowlist) {
			String normalized = allowed.toLowerCase(Locale.ROOT);
			if (normalized.equals(uuid) || normalized.equals(name)) {
				return true;
			}
		}
		return server.getPlayerList().isOp(player.nameAndId());
	}

	public boolean isDangerousCommand(String command) {
		String normalized = command.trim();
		while (normalized.startsWith("/")) {
			normalized = normalized.substring(1).trim();
		}
		if (normalized.isEmpty()) {
			return true;
		}
		String verb = normalized.split("\\s+", 2)[0].toLowerCase(Locale.ROOT);
		for (String denied : dangerousCommandDenylist) {
			if (verb.equals(denied.toLowerCase(Locale.ROOT))) {
				return true;
			}
		}
		return false;
	}

	public void allow(String playerOrUuid) {
		if (!actionAllowlist.contains(playerOrUuid)) {
			actionAllowlist.add(playerOrUuid);
			save();
		}
	}

	public void deny(String playerOrUuid) {
		actionAllowlist.removeIf(value -> value.equalsIgnoreCase(playerOrUuid));
		save();
	}

	private void normalize() {
		if (path == null) {
			path = FabricLoader.getInstance().getConfigDir().resolve(CONFIG_FILE);
		}
		if (sidecarBaseUrl == null || sidecarBaseUrl.isBlank()) {
			sidecarBaseUrl = "http://127.0.0.1:18911";
		}
		sidecarBaseUrl = sidecarBaseUrl.replaceAll("/+$", "");
		if (sidecarTimeoutMs <= 0) {
			sidecarTimeoutMs = 60000;
		}
		if (actionAllowlist == null) {
			actionAllowlist = new ArrayList<>();
		}
		if (bodyUsername == null || bodyUsername.isBlank()) {
			bodyUsername = "mina";
		}
		if (snapshotIntervalTicks < 20) {
			snapshotIntervalTicks = 20;
		}
		if (nearbyEntityRadius < 8) {
			nearbyEntityRadius = 8;
		}
		if (maxInventorySlotsReported < 1) {
			maxInventorySlotsReported = 46;
		}
		if (maxNearbyEntitiesReported < 1) {
			maxNearbyEntitiesReported = 80;
		}
		if (dangerousCommandDenylist == null || dangerousCommandDenylist.isEmpty()) {
			dangerousCommandDenylist = new ArrayList<>(List.of("op", "deop", "stop", "ban", "whitelist"));
		}
	}
}
