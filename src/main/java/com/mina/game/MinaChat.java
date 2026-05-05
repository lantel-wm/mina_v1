package com.mina.game;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;

final class MinaChat {
	private static final int CHAT_CHUNK_LIMIT = 240;

	private MinaChat() {
	}

	static void sendMina(ServerPlayer player, String content) {
		send(player, minaPrefix(), ChatFormatting.WHITE, content);
	}

	static void broadcastMina(MinecraftServer server, String content) {
		broadcast(server, minaPrefix(), ChatFormatting.WHITE, content);
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
		for (String chunk : chatChunks(content)) {
			player.sendSystemMessage(line(prefix, chunk, bodyStyles));
		}
	}

	private static void broadcast(MinecraftServer server, Component prefix, ChatFormatting bodyStyle, String content) {
		if (server == null || content == null || content.isBlank()) {
			return;
		}
		for (String chunk : chatChunks(content)) {
			server.getPlayerList().broadcastSystemMessage(line(prefix, chunk, bodyStyle), false);
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

	private static List<String> chatChunks(String content) {
		List<String> chunks = new ArrayList<>();
		for (String rawLine : content.split("\\R", -1)) {
			String line = rawLine.strip();
			if (line.isBlank()) {
				continue;
			}
			while (line.length() > CHAT_CHUNK_LIMIT) {
				int split = bestSplit(line, CHAT_CHUNK_LIMIT);
				chunks.add(line.substring(0, split).strip());
				line = line.substring(split).strip();
			}
			if (!line.isBlank()) {
				chunks.add(line);
			}
		}
		return chunks;
	}

	private static int bestSplit(String line, int limit) {
		int split = Math.min(limit, line.length());
		for (int index = split; index > Math.max(0, split - 40); index--) {
			char current = line.charAt(index - 1);
			if (Character.isWhitespace(current) || current == '，' || current == ',' || current == '。' || current == '.') {
				return index;
			}
		}
		return split;
	}
}
