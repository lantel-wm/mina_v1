package com.mina.game;

import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;

final class MinaChat {
	private static final int CHAT_CHUNK_LIMIT = 240;

	private MinaChat() {
	}

	static void send(ServerPlayer player, String prefix, String content) {
		if (player == null || content == null || content.isBlank()) {
			return;
		}
		for (String chunk : chatChunks(content)) {
			player.sendSystemMessage(Component.literal(prefix + chunk));
		}
	}

	static void broadcast(MinecraftServer server, String prefix, String content) {
		if (server == null || content == null || content.isBlank()) {
			return;
		}
		for (String chunk : chatChunks(content)) {
			server.getPlayerList().broadcastSystemMessage(Component.literal(prefix + chunk), false);
		}
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
