package com.mina.game;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import net.minecraft.commands.CommandResultCallback;
import net.minecraft.commands.CommandSource;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.permissions.PermissionSet;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

public final class MinaActionExecutor {
	private static final Pattern IDENTIFIER = Pattern.compile("[a-z0-9_:.\\-/#]+");
	private static final Set<String> READ_ONLY_TIME_QUERIES = Set.of("daytime", "gametime", "day");
	private final ThreadLocal<List<CommandExecution>> commandLog = ThreadLocal.withInitial(ArrayList::new);

	public JsonArray executeResponse(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject response) {
		if (response == null) {
			return new JsonArray();
		}
		MinaMod.LOGGER.info("mina execute response messages={} actions={}", count(response.getAsJsonArray("messages")), count(response.getAsJsonArray("actions")));
		sendMessages(server, requester, response.getAsJsonArray("messages"));
		return executeActions(server, requester, config, response.getAsJsonArray("actions"));
	}

	private void sendMessages(MinecraftServer server, ServerPlayer requester, JsonArray messages) {
		if (messages == null) {
			return;
		}
		for (JsonElement element : messages) {
			if (!element.isJsonObject()) {
				continue;
			}
			JsonObject message = element.getAsJsonObject();
			String content = string(message, "content", "");
			if (content.isBlank()) {
				continue;
			}
			String target = string(message, "target", "requester");
			MinaMod.LOGGER.info("mina send message target={} content={}", target, content);
			if ("all".equalsIgnoreCase(target)) {
				broadcast(server, content);
			} else if (requester != null) {
				message(requester, content);
			}
		}
	}

	private JsonArray executeActions(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonArray actions) {
		JsonArray results = new JsonArray();
		if (actions == null) {
			return results;
		}
		for (JsonElement element : actions) {
			if (!element.isJsonObject()) {
				continue;
			}
			JsonObject action = element.getAsJsonObject();
			String name = string(action, "name", "");
			JsonObject args = action.has("args") && action.get("args").isJsonObject()
				? action.getAsJsonObject("args")
				: new JsonObject();
			boolean requiresPermission = bool(action, "requires_permission", false);
			MinaMod.LOGGER.info("mina action start name={} requiresPermission={} args={}", name, requiresPermission, args);
			List<CommandExecution> commands = commandLog.get();
			commands.clear();
			JsonObject result = baseActionResult(action, name);
			if (requiresPermission && !config.canUseActions(server, requester)) {
				MinaMod.LOGGER.info("mina action denied name={} player={}", name, requester == null ? "<server>" : requester.getGameProfile().name());
				message(requester, "Action denied by Mina permissions.");
				result.addProperty("status", "permission_denied");
				result.addProperty("command_success", false);
				result.addProperty("error", "permission denied");
				results.add(result);
				continue;
			}
			try {
				executeAction(server, requester, name, args);
				result.add("command_results", commandResults(commands));
				boolean commandSuccess = commandSuccess(commands);
				result.addProperty("command_success", commandSuccess);
				if (!commandSuccess) {
					result.addProperty("status", "command_failed");
					result.addProperty("error", "one or more Minecraft commands failed");
				} else {
					result.addProperty("status", "completed");
				}
			} catch (RuntimeException exception) {
				MinaMod.LOGGER.warn("Failed to execute Mina action {}", name, exception);
				message(requester, "Mina action failed: " + exception.getMessage());
				result.add("command_results", commandResults(commands));
				result.addProperty("command_success", false);
				result.addProperty("status", "failed");
				result.addProperty("error", exception.getMessage());
			}
			results.add(result);
		}
		return results;
	}

	private void executeAction(MinecraftServer server, ServerPlayer requester, String name, JsonObject args) {
		switch (name) {
			case "send_player_message" -> message(requester, string(args, "content", ""));
			case "send_global_message" -> broadcast(server, string(args, "content", ""));
			case "run_safe_command", "run_read_only_command" -> runReadOnlyCommand(server, requester, string(args, "command", ""));
			case "locate_structure" -> locateStructure(server, requester, string(args, "structure", ""));
			default -> throw new IllegalArgumentException("unknown Mina action " + name);
		}
	}

	private void runReadOnlyCommand(MinecraftServer server, ServerPlayer requester, String command) {
		String normalized = stripSlash(command);
		if (normalized.isBlank() || !isReadOnlyCommand(normalized)) {
			MinaMod.LOGGER.info("mina read-only command refused command={}", command);
			throw new IllegalArgumentException("Only read-only Minecraft commands are allowed.");
		}
		if ("weather query".equalsIgnoreCase(normalized)) {
			reportWeatherQuery(server, requester);
			return;
		}
		runCommand(server, requester, normalized);
	}

	private void reportWeatherQuery(MinecraftServer server, ServerPlayer requester) {
		var level = requester == null ? server.overworld() : requester.level();
		String weather = level.isThundering() ? "thunder" : level.isRaining() ? "rain" : "clear";
		String output = "Weather: " + weather;
		CommandExecution execution = new CommandExecution("weather query");
		execution.addOutput(output);
		execution.setResult(true, 1);
		commandLog.get().add(execution);
		MinaMod.LOGGER.info("mina command output command={} message={}", execution.command(), output);
		MinaMod.LOGGER.info("mina command callback command={} success={} result={}", execution.command(), true, 1);
		commandOutput(requester, output);
	}

	private void locateStructure(MinecraftServer server, ServerPlayer requester, String structure) {
		String normalized = structure.toLowerCase(Locale.ROOT);
		if (!IDENTIFIER.matcher(normalized).matches()) {
			MinaMod.LOGGER.info("mina locate refused invalid structure={}", structure);
			message(requester, "Invalid structure identifier.");
			return;
		}
		runCommand(server, requester, "locate structure " + normalized);
	}

	private CommandExecution runCommand(MinecraftServer server, ServerPlayer requester, String command) {
		MinaMod.LOGGER.info("mina run command as={} command={}", requester == null ? "<server>" : requester.getGameProfile().name(), stripSlash(command));
		CommandExecution execution = new CommandExecution(stripSlash(command));
		CommandSourceStack source = requester == null
			? server.createCommandSourceStack()
			: requester.createCommandSourceStack();
		CommandSource loggingSource = new LoggingCommandSource(requester, execution);
		CommandResultCallback callback = (success, result) -> {
			execution.setResult(success, result);
			MinaMod.LOGGER.info("mina command callback command={} success={} result={}", execution.command(), success, result);
		};
		source = source
			.withSource(loggingSource)
			.withMaximumPermission(PermissionSet.ALL_PERMISSIONS)
			.withCallback(callback);
		server.getCommands().performPrefixedCommand(source, stripSlash(command));
		commandLog.get().add(execution);
		return execution;
	}

	private static JsonObject baseActionResult(JsonObject action, String name) {
		JsonObject result = new JsonObject();
		result.addProperty("action_id", string(action, "id", ""));
		result.addProperty("task_id", string(action, "task_id", ""));
		result.addProperty("step_id", string(action, "step_id", ""));
		result.addProperty("name", name);
		if (action.has("expected_effect") && action.get("expected_effect").isJsonObject()) {
			result.add("expected_effect", action.getAsJsonObject("expected_effect"));
		}
		return result;
	}

	private static JsonArray commandResults(List<CommandExecution> commands) {
		JsonArray array = new JsonArray();
		for (CommandExecution command : commands) {
			JsonObject json = new JsonObject();
			json.addProperty("command", command.command());
			json.addProperty("completed", command.completed());
			json.addProperty("success", command.success());
			json.addProperty("result", command.result());
			JsonArray outputs = new JsonArray();
			for (String output : command.outputs()) {
				outputs.add(output);
			}
			json.add("outputs", outputs);
			array.add(json);
		}
		return array;
	}

	private static boolean commandSuccess(List<CommandExecution> commands) {
		if (commands.isEmpty()) {
			return true;
		}
		for (CommandExecution command : commands) {
			if (!command.success()) {
				return false;
			}
		}
		return true;
	}

	private static void message(ServerPlayer player, String content) {
		MinaChat.sendMina(player, content);
	}

	private static void commandOutput(ServerPlayer player, String content) {
		if (player != null && content != null && !content.isBlank()) {
			MinaMod.LOGGER.info("mina send command output content={}", content);
			MinaChat.sendCommandOutput(player, content);
		}
	}

	private static void broadcast(MinecraftServer server, String content) {
		MinaChat.broadcastMina(server, content);
	}

	private static String stripSlash(String command) {
		String normalized = command == null ? "" : command.trim();
		while (normalized.startsWith("/")) {
			normalized = normalized.substring(1).trim();
		}
		return normalized.replaceAll("\\s+", " ");
	}

	private static boolean isReadOnlyCommand(String command) {
		String normalized = stripSlash(command).toLowerCase(Locale.ROOT);
		String[] parts = normalized.isBlank() ? new String[0] : normalized.split("\\s+");
		if (parts.length == 1 && parts[0].equals("seed")) {
			return true;
		}
		if (parts.length == 3 && parts[0].equals("time") && parts[1].equals("query") && READ_ONLY_TIME_QUERIES.contains(parts[2])) {
			return true;
		}
		if (parts.length == 2 && parts[0].equals("weather") && parts[1].equals("query")) {
			return true;
		}
		if (parts.length == 1 && parts[0].equals("list")) {
			return true;
		}
		if (parts.length == 2 && parts[0].equals("list") && parts[1].equals("uuids")) {
			return true;
		}
		return parts.length == 3
			&& parts[0].equals("locate")
			&& (parts[1].equals("structure") || parts[1].equals("biome"))
			&& IDENTIFIER.matcher(parts[2]).matches();
	}

	private static String string(JsonObject object, String key, String fallback) {
		if (!object.has(key) || object.get(key).isJsonNull()) {
			return fallback;
		}
		return object.get(key).getAsString();
	}

	private static boolean bool(JsonObject object, String key, boolean fallback) {
		if (!object.has(key) || object.get(key).isJsonNull()) {
			return fallback;
		}
		return object.get(key).getAsBoolean();
	}

	private static int count(JsonArray array) {
		return array == null ? 0 : array.size();
	}

	private static final class CommandExecution {
		private final String command;
		private final List<String> outputs = new ArrayList<>();
		private boolean completed;
		private boolean success;
		private int result;

		private CommandExecution(String command) {
			this.command = command;
		}

		private String command() {
			return command;
		}

		private boolean success() {
			return completed && success;
		}

		private boolean completed() {
			return completed;
		}

		private int result() {
			return result;
		}

		private List<String> outputs() {
			return outputs;
		}

		private void addOutput(String output) {
			outputs.add(output);
		}

		private void setResult(boolean success, int result) {
			this.completed = true;
			this.success = success;
			this.result = result;
		}
	}

	private static final class LoggingCommandSource implements CommandSource {
		private final ServerPlayer requester;
		private final CommandExecution execution;

		private LoggingCommandSource(ServerPlayer requester, CommandExecution execution) {
			this.requester = requester;
			this.execution = execution;
		}

		@Override
		public void sendSystemMessage(Component message) {
			execution.addOutput(message.getString());
			MinaMod.LOGGER.info("mina command output command={} message={}", execution.command(), message.getString());
			commandOutput(requester, message.getString());
		}

		@Override
		public boolean acceptsSuccess() {
			return true;
		}

		@Override
		public boolean acceptsFailure() {
			return true;
		}

		@Override
		public boolean shouldInformAdmins() {
			return false;
		}
	}
}
