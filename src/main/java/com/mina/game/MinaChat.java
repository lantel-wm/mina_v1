package com.mina.game;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

final class MinaChat {
	private static final int CHAT_COLUMN_LIMIT = 58;
	private static final Pattern NUMBERED_ITEM_BOUNDARY = Pattern.compile("\\s+(?=\\d+[.．、]\\s*[^0-9\\s])");

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

	private static List<String> chatChunks(String content) {
		List<String> chunks = new ArrayList<>();
		String normalized = NUMBERED_ITEM_BOUNDARY.matcher(content).replaceAll("\n");
		for (String rawLine : normalized.split("\\R", -1)) {
			String line = rawLine.strip();
			if (line.isBlank()) {
				continue;
			}
			while (displayWidth(line) > CHAT_COLUMN_LIMIT) {
				int split = bestSplit(line, CHAT_COLUMN_LIMIT);
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
		int width = 0;
		int fallback = 0;
		int preferred = 0;
		for (int offset = 0; offset < line.length();) {
			int codePoint = line.codePointAt(offset);
			int next = offset + Character.charCount(codePoint);
			width += characterWidth(codePoint);
			if (width > limit) {
				if (preferred > 0) {
					return preferred;
				}
				return fallback > 0 ? fallback : next;
			}
			fallback = next;
			if (isBreakCharacter(codePoint)) {
				preferred = next;
			}
			offset = next;
		}
		return line.length();
	}

	private static int displayWidth(String value) {
		int width = 0;
		for (int offset = 0; offset < value.length();) {
			int codePoint = value.codePointAt(offset);
			width += characterWidth(codePoint);
			offset += Character.charCount(codePoint);
		}
		return width;
	}

	private static int characterWidth(int codePoint) {
		Character.UnicodeBlock block = Character.UnicodeBlock.of(codePoint);
		if (block == Character.UnicodeBlock.CJK_UNIFIED_IDEOGRAPHS
			|| block == Character.UnicodeBlock.CJK_UNIFIED_IDEOGRAPHS_EXTENSION_A
			|| block == Character.UnicodeBlock.CJK_COMPATIBILITY_IDEOGRAPHS
			|| block == Character.UnicodeBlock.HALFWIDTH_AND_FULLWIDTH_FORMS
			|| block == Character.UnicodeBlock.HIRAGANA
			|| block == Character.UnicodeBlock.KATAKANA
			|| block == Character.UnicodeBlock.HANGUL_SYLLABLES) {
			return 2;
		}
		return 1;
	}

	private static boolean isBreakCharacter(int codePoint) {
		return Character.isWhitespace(codePoint)
			|| codePoint == '，'
			|| codePoint == ','
			|| codePoint == '。'
			|| codePoint == '.'
			|| codePoint == '；'
			|| codePoint == ';'
			|| codePoint == '：'
			|| codePoint == ':';
	}
}
