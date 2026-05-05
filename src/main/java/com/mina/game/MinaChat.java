package com.mina.game;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;

final class MinaChat {
	private MinaChat() {
	}

	static void sendMina(ServerPlayer player, String content) {
		send(player, minaPrefix(), ChatFormatting.WHITE, formatMinaContent(content));
	}

	static void broadcastMina(MinecraftServer server, String content) {
		broadcast(server, minaPrefix(), ChatFormatting.WHITE, formatMinaContent(content));
	}

	static void sendPlayerEcho(ServerPlayer player, String content) {
		if (player == null) {
			return;
		}
		var prefix = Component.empty()
			.append(Component.literal("[").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal(player.getGameProfile().name()).withStyle(ChatFormatting.GOLD))
			.append(Component.literal("] ").withStyle(ChatFormatting.DARK_GRAY));
		send(player, prefix, ChatFormatting.GRAY, content);
	}

	static void sendThinking(ServerPlayer player) {
		send(player, minaPrefix(), "正在思考...", ChatFormatting.GRAY, ChatFormatting.ITALIC);
	}

	static void sendCommandOutput(ServerPlayer player, String content) {
		var prefix = Component.empty()
			.append(Component.literal("[").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal("查询结果").withStyle(ChatFormatting.DARK_AQUA))
			.append(Component.literal("] ").withStyle(ChatFormatting.DARK_GRAY));
		send(player, prefix, ChatFormatting.GRAY, content);
	}

	static void sendProgress(ServerPlayer player, String content) {
		var prefix = Component.empty()
			.append(Component.literal("[").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal("Mina").withStyle(ChatFormatting.DARK_AQUA))
			.append(Component.literal("] ").withStyle(ChatFormatting.DARK_GRAY));
		send(player, prefix, content, ChatFormatting.DARK_AQUA, ChatFormatting.ITALIC);
	}

	static void sendError(ServerPlayer player, String content) {
		send(player, errorPrefix(), ChatFormatting.RED, content);
	}

	static Component failure(String content) {
		return Component.empty()
			.append(errorPrefix())
			.append(Component.literal(content).withStyle(ChatFormatting.RED));
	}

	static Component success(String content) {
		return Component.empty()
			.append(Component.literal("[").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal("Mina").withStyle(ChatFormatting.GREEN))
			.append(Component.literal("] ").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal(content).withStyle(ChatFormatting.GREEN));
	}

	static Component notice(String content) {
		return Component.empty()
			.append(minaPrefix())
			.append(Component.literal(content).withStyle(ChatFormatting.YELLOW));
	}

	private static void send(ServerPlayer player, Component prefix, ChatFormatting bodyStyle, String content) {
		send(player, prefix, content, bodyStyle);
	}

	private static void send(ServerPlayer player, Component prefix, String content, ChatFormatting... bodyStyles) {
		if (player == null || content == null || content.isBlank()) {
			return;
		}
		boolean first = true;
		for (String chunk : chatChunks(content)) {
			player.sendSystemMessage(line(first ? prefix : continuationPrefix(), chunk, bodyStyles));
			first = false;
		}
	}

	private static void broadcast(MinecraftServer server, Component prefix, ChatFormatting bodyStyle, String content) {
		if (server == null || content == null || content.isBlank()) {
			return;
		}
		boolean first = true;
		for (String chunk : chatChunks(content)) {
			server.getPlayerList().broadcastSystemMessage(line(first ? prefix : continuationPrefix(), chunk, bodyStyle), false);
			first = false;
		}
	}

	private static Component line(Component prefix, String chunk, ChatFormatting... bodyStyles) {
		return Component.empty()
			.append(prefix.copy())
			.append(Component.literal(chunk).withStyle(bodyStyles));
	}

	private static Component minaPrefix() {
		return Component.empty()
			.append(Component.literal("[").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal("Mina").withStyle(ChatFormatting.AQUA))
			.append(Component.literal("] ").withStyle(ChatFormatting.DARK_GRAY));
	}

	private static Component errorPrefix() {
		return Component.empty()
			.append(Component.literal("[").withStyle(ChatFormatting.DARK_GRAY))
			.append(Component.literal("Mina").withStyle(ChatFormatting.RED))
			.append(Component.literal("] ").withStyle(ChatFormatting.DARK_GRAY));
	}

	private static Component continuationPrefix() {
		return Component.empty();
	}

	private static String formatMinaContent(String content) {
		if (content == null || content.isBlank()) {
			return "";
		}
		return content.replaceAll("\\s+", " ").strip();
	}

	private static List<String> chatChunks(String content) {
		List<String> chunks = new ArrayList<>();
		for (String rawLine : content.split("\\R", -1)) {
			String line = rawLine.strip();
			if (!line.isBlank()) {
				chunks.add(line);
			}
		}
		return chunks;
	}
}
