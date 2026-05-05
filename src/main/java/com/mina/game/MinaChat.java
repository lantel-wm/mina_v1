package com.mina.game;

import net.minecraft.ChatFormatting;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

final class MinaChat {
	private static final Pattern SECTION_LABEL = Pattern.compile(
		"\\s*(材料清单|需要材料|建造步骤|步骤|原理|注意|建议|提示|简化的建法|简化建法|建法|来源|参考)\\s*([:：])\\s*"
	);
	private static final Pattern NUMBERED_ITEM_BOUNDARY = Pattern.compile("\\s+(?=(?:\\d{1,2}[.．、]|[一二三四五六七八九十]+[、.．])\\s*[^0-9\\s])");

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
		String formatted = content.replace("\r\n", "\n").replace('\r', '\n');
		formatted = SECTION_LABEL.matcher(formatted).replaceAll("\n$1$2\n");
		formatted = NUMBERED_ITEM_BOUNDARY.matcher(formatted).replaceAll("\n");
		return formatted.replaceAll("\\n{3,}", "\n\n").strip();
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
