package com.mina.game;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mina.MinaMod;
import com.mina.config.MinaConfig;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.commands.CommandResultCallback;
import net.minecraft.commands.CommandSource;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.permissions.PermissionSet;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

public final class MinaActionExecutor {
	private static final Pattern BODY_NAME = Pattern.compile("[A-Za-z0-9_]{1,16}");
	private static final Pattern SELECTOR = Pattern.compile("[A-Za-z0-9_:@\\[\\]=,.!\\-]+");
	private static final Pattern IDENTIFIER = Pattern.compile("[a-z0-9_:.\\-/#]+");
	private static final double BODY_EYE_HEIGHT = 1.62D;
	private static final Set<String> READ_ONLY_COMMAND_PREFIXES = Set.of("seed", "time query", "weather query", "list", "locate structure");
	private final ThreadLocal<List<CommandExecution>> commandLog = ThreadLocal.withInitial(ArrayList::new);

	public JsonArray executeResponse(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject response) {
		if (response == null) {
			return new JsonArray();
		}
		MinaMod.LOGGER.info("mina execute response messages={} actions={}", count(response.getAsJsonArray("messages")), count(response.getAsJsonArray("actions")));
		sendMessages(server, requester, response.getAsJsonArray("messages"));
		return executeActions(server, requester, config, response.getAsJsonArray("actions"));
	}

	public void stopBody(MinecraftServer server, ServerPlayer requester, MinaConfig config) {
		if (!isBodyAvailable(config)) {
			message(requester, "Mina body is unavailable because PuppetPlayers is not installed or body use is disabled.");
			return;
		}
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run minecraft:interrupt_move_to");
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run minecraft:attack release");
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run minecraft:use release");
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions chain stop");
	}

	public boolean isBodyAvailable(MinaConfig config) {
		return config.enableBody && FabricLoader.getInstance().isModLoaded("puppet-players") && BODY_NAME.matcher(config.bodyUsername).matches();
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
				server.getPlayerList().broadcastSystemMessage(Component.literal("[Mina] " + content), false);
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
				executeAction(server, requester, config, name, args);
				result.add("command_results", commandResults(commands));
				boolean commandSuccess = commandSuccess(commands);
				result.addProperty("command_success", commandSuccess);
				if (!commandSuccess) {
					result.addProperty("status", "command_failed");
					result.addProperty("error", "one or more Minecraft commands failed");
				} else if (action.has("monitor") && action.get("monitor").isJsonObject()) {
					result.addProperty("status", "monitor_pending");
					result.add("monitor", action.getAsJsonObject("monitor"));
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

	private void executeAction(MinecraftServer server, ServerPlayer requester, MinaConfig config, String name, JsonObject args) {
		switch (name) {
			case "send_player_message" -> message(requester, string(args, "content", ""));
			case "send_global_message" -> server.getPlayerList().broadcastSystemMessage(Component.literal("[Mina] " + string(args, "content", "")), false);
			case "run_safe_command", "run_read_only_command" -> runReadOnlyCommand(server, requester, string(args, "command", ""));
			case "locate_structure" -> locateStructure(server, requester, string(args, "structure", ""));
			case "body_spawn" -> bodySpawn(server, requester, config);
			case "body_move_to_position" -> bodyMoveToPosition(server, requester, config, args);
			case "body_move_to_entity" -> bodyMoveToEntity(server, requester, config, args);
			case "body_move_to_requester" -> bodyMoveToRequester(server, requester, config, args);
			case "body_look_at_position" -> bodyLookAtPosition(server, requester, config, args);
			case "body_look_at_entity" -> bodyLookAtEntity(server, requester, config, args);
			case "body_look_at_requester" -> bodyLookAtRequester(server, requester, config, args);
			case "body_move_to" -> bodyMoveTo(server, requester, config, args);
			case "body_look_at" -> bodyLookAt(server, requester, config, args);
			case "body_attack" -> puppetAction(server, requester, config, "minecraft:attack " + mode(args));
			case "body_use" -> puppetAction(server, requester, config, "minecraft:use " + mode(args));
			case "body_delay" -> throw new IllegalArgumentException("body_delay only works inside PuppetPlayers action chains; use body_chain");
			case "body_chain" -> bodyChain(server, requester, config, args);
			case "body_swap_slot" -> puppetAction(server, requester, config, "minecraft:swap_slot " + clampInt(args, "slot", 0, 0, 8));
			case "body_stop" -> stopBody(server, requester, config);
			default -> throw new IllegalArgumentException("unknown Mina action " + name);
		}
	}

	private void runReadOnlyCommand(MinecraftServer server, ServerPlayer requester, String command) {
		String normalized = stripSlash(command);
		if (normalized.isBlank() || !isReadOnlyCommand(normalized)) {
			MinaMod.LOGGER.info("mina read-only command refused command={}", command);
			message(requester, "Mina refused a non-read-only command.");
			return;
		}
		runCommand(server, requester, normalized);
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

	private void bodySpawn(MinecraftServer server, ServerPlayer requester, MinaConfig config) {
		requireBodyAvailable(config);
		CommandExecution execution = runCommand(server, requester, "puppet " + config.bodyUsername + " spawn");
		ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
		if (body == null) {
			MinaMod.LOGGER.warn(
				"mina body spawn not confirmed commandSuccess={} commandResult={} bodyOnline={}",
				execution.success(),
				execution.result(),
				body != null
			);
			message(requester, "I tried to spawn the body, but it is not online yet. Check the server log for the PuppetPlayers command result.");
		} else {
			MinaMod.LOGGER.info(
				"mina body spawn confirmed username={} uuid={} commandSuccess={} commandResult={}",
				body.getGameProfile().name(),
				body.getUUID(),
				execution.success(),
				execution.result()
			);
		}
	}

	private void bodyMoveTo(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		String targetType = string(args, "target_type", "position");
		boolean sprint = bool(args, "sprint", true);
		boolean jump = bool(args, "jump", true);
		if ("requester".equals(targetType)) {
			puppetAction(server, requester, config, "minecraft:move_to entity " + requesterSelector(requester) + " " + sprint + " " + jump);
			return;
		}
		if ("entity".equals(targetType)) {
			String selector = selector(args);
			puppetAction(server, requester, config, "minecraft:move_to entity " + selector + " " + sprint + " " + jump);
			return;
		}
		if (!hasPosition(args)) {
			throw new IllegalArgumentException("body_move_to requires target_type=requester, target_type=entity with entity_selector, or target_type=position with x/y/z");
		}
		puppetAction(server, requester, config, "minecraft:move_to position " + position(args) + " " + sprint + " " + jump);
	}

	private void bodyMoveToPosition(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		boolean sprint = bool(args, "sprint", true);
		boolean jump = bool(args, "jump", true);
		puppetAction(server, requester, config, "minecraft:move_to position " + position(args) + " " + sprint + " " + jump);
	}

	private void bodyMoveToEntity(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		boolean sprint = bool(args, "sprint", true);
		boolean jump = bool(args, "jump", true);
		puppetAction(server, requester, config, "minecraft:move_to entity " + selector(args) + " " + sprint + " " + jump);
	}

	private void bodyMoveToRequester(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		boolean sprint = bool(args, "sprint", true);
		boolean jump = bool(args, "jump", true);
		puppetAction(server, requester, config, "minecraft:move_to entity " + requesterSelector(requester) + " " + sprint + " " + jump);
	}

	private void bodyLookAt(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		String targetType = string(args, "target_type", "position");
		if ("requester".equals(targetType)) {
			bodyLookAtRequester(server, requester, config, args);
			return;
		}
		if ("entity".equals(targetType)) {
			throw new IllegalArgumentException("body_look_at entity targets are not supported by PuppetPlayers 1.21.11; use body_look_at_position");
		}
		if (!hasPosition(args)) {
			throw new IllegalArgumentException("body_look_at requires target_type=requester, target_type=entity with entity_selector, or target_type=position with x/y/z");
		}
		bodyLookAtPosition(server, requester, config, args);
	}

	private void bodyLookAtPosition(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		puppetAction(server, requester, config, lookAction(bodyEyePosition(server, config), targetPosition(args)));
	}

	private void bodyLookAtEntity(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		throw new IllegalArgumentException("body_look_at_entity is not supported by PuppetPlayers 1.21.11; use body_look_at_position");
	}

	private void bodyLookAtRequester(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		if (requester == null) {
			throw new IllegalArgumentException("missing requester for body_look_at_requester");
		}
		JsonObject position = new JsonObject();
		position.addProperty("x", requester.getX());
		position.addProperty("y", requester.getEyeY());
		position.addProperty("z", requester.getZ());
		puppetAction(server, requester, config, lookAction(bodyEyePosition(server, config), targetPosition(position)));
	}

	private void bodyChain(MinecraftServer server, ServerPlayer requester, MinaConfig config, JsonObject args) {
		requireBodyAvailable(config);
		if (!args.has("actions") || !args.get("actions").isJsonArray()) {
			throw new IllegalArgumentException("body_chain requires actions array");
		}
		boolean clear = bool(args, "clear", true);
		boolean loop = bool(args, "loop", false);
		boolean restart = bool(args, "restart", true);
		if (clear) {
			clearBodyControls(server, requester, config);
		}
		JsonArray actions = args.getAsJsonArray("actions");
		if (actions.size() == 0) {
			throw new IllegalArgumentException("body_chain actions cannot be empty");
		}
		Vec3 lookOrigin = bodyEyePosition(server, config);
		for (JsonElement element : actions) {
			if (!element.isJsonObject()) {
				throw new IllegalArgumentException("body_chain actions must be objects");
			}
			ChainCommand chainAction = chainAction(requester, element.getAsJsonObject(), lookOrigin);
			CommandExecution execution = runCommand(server, requester, "puppet " + config.bodyUsername + " actions chain add " + chainAction.command());
			if (!execution.success()) {
				runCommand(server, requester, "puppet " + config.bodyUsername + " actions chain stop");
				throw new IllegalArgumentException("failed to add body_chain action " + chainAction.command());
			}
			if (chainAction.nextLookOrigin() != null) {
				lookOrigin = chainAction.nextLookOrigin();
			}
		}
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions chain loop " + loop);
		if (restart) {
			runCommand(server, requester, "puppet " + config.bodyUsername + " actions chain restart");
		}
	}

	private void clearBodyControls(MinecraftServer server, ServerPlayer requester, MinaConfig config) {
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run minecraft:interrupt_move_to");
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run minecraft:attack release");
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run minecraft:use release");
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions chain stop");
	}

	private ChainCommand chainAction(ServerPlayer requester, JsonObject action, Vec3 lookOrigin) {
		String type = string(action, "type", "").toLowerCase(Locale.ROOT);
		return switch (type) {
			case "move_to_position" -> {
				Vec3 nextOrigin = new Vec3(coordDouble(action, "x"), coordDouble(action, "y") + BODY_EYE_HEIGHT, coordDouble(action, "z"));
				yield new ChainCommand("minecraft:move_to position " + position(action) + " " + bool(action, "sprint", true) + " " + bool(action, "jump", true), nextOrigin);
			}
			case "move_to_requester" -> new ChainCommand("minecraft:move_to entity " + requesterSelector(requester) + " " + bool(action, "sprint", true) + " " + bool(action, "jump", true), null);
			case "look_at_position" -> new ChainCommand(lookAction(lookOrigin, targetPosition(action)), null);
			case "look_at_requester" -> new ChainCommand(lookAction(lookOrigin, requesterEyePosition(requester)), null);
			case "attack" -> new ChainCommand("minecraft:attack " + mode(action), null);
			case "use" -> new ChainCommand("minecraft:use " + mode(action), null);
			case "delay" -> new ChainCommand("minecraft:delay " + delay(action), null);
			case "swap_slot" -> new ChainCommand("minecraft:swap_slot " + clampInt(action, "slot", 0, 0, 8), null);
			default -> throw new IllegalArgumentException("unsupported body_chain action type " + type);
		};
	}

	private void puppetAction(MinecraftServer server, ServerPlayer requester, MinaConfig config, String action) {
		requireBodyAvailable(config);
		runCommand(server, requester, "puppet " + config.bodyUsername + " actions run " + action);
	}

	private void requireBodyAvailable(MinaConfig config) {
		if (!isBodyAvailable(config)) {
			MinaMod.LOGGER.info("mina body unavailable enableBody={} bodyUsername={}", config.enableBody, config.bodyUsername);
			throw new IllegalArgumentException("Mina body is unavailable because PuppetPlayers is not installed or body use is disabled.");
		}
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
		if (player != null && content != null && !content.isBlank()) {
			player.sendSystemMessage(Component.literal("[Mina] " + content));
		}
	}

	private static String mode(JsonObject args) {
		String mode = string(args, "mode", "once").toLowerCase(Locale.ROOT);
		return switch (mode) {
			case "hold", "release" -> mode;
			default -> "once";
		};
	}

	private static String lookAction(Vec3 origin, Vec3 target) {
		double dx = target.x - origin.x;
		double dy = target.y - origin.y;
		double dz = target.z - origin.z;
		double horizontalDistance = Math.sqrt(dx * dx + dz * dz);
		double yaw = Math.toDegrees(Math.atan2(dz, dx)) - 90.0D;
		double pitch = -Math.toDegrees(Math.atan2(dy, horizontalDistance));
		pitch = Math.max(-90.0D, Math.min(90.0D, pitch));
		return String.format(Locale.ROOT, "minecraft:look %.2f %.2f", wrapDegrees(yaw), pitch);
	}

	private static double wrapDegrees(double degrees) {
		double wrapped = degrees % 360.0D;
		if (wrapped >= 180.0D) {
			wrapped -= 360.0D;
		}
		if (wrapped < -180.0D) {
			wrapped += 360.0D;
		}
		return wrapped;
	}

	private static Vec3 bodyEyePosition(MinecraftServer server, MinaConfig config) {
		ServerPlayer body = server.getPlayerList().getPlayer(config.bodyUsername);
		if (body == null) {
			throw new IllegalArgumentException("Mina body is not online");
		}
		return new Vec3(body.getX(), body.getEyeY(), body.getZ());
	}

	private static Vec3 requesterEyePosition(ServerPlayer requester) {
		if (requester == null) {
			throw new IllegalArgumentException("missing requester for look_at_requester");
		}
		return new Vec3(requester.getX(), requester.getEyeY(), requester.getZ());
	}

	private static Vec3 targetPosition(JsonObject args) {
		return new Vec3(coordDouble(args, "x"), coordDouble(args, "y"), coordDouble(args, "z"));
	}

	private static String delay(JsonObject args) {
		double seconds = args.has("seconds") ? args.get("seconds").getAsDouble() : 1.0D;
		seconds = Math.max(0.1D, Math.min(30.0D, seconds));
		int ticks = Math.max(1, Math.min(600, (int) Math.ceil(seconds * 20.0D)));
		return ticks + "t";
	}

	private static String selector(JsonObject args) {
		String selector = string(args, "entity_selector", "");
		if (selector.isBlank()) {
			throw new IllegalArgumentException("missing entity_selector");
		}
		if (!SELECTOR.matcher(selector).matches()) {
			throw new IllegalArgumentException("invalid entity selector");
		}
		return selector;
	}

	private static String requesterSelector(ServerPlayer requester) {
		if (requester == null) {
			return "@p";
		}
		String name = requester.getGameProfile().name();
		if (!SELECTOR.matcher(name).matches()) {
			return "@p";
		}
		return "@a[name=" + name + ",limit=1]";
	}

	private static boolean hasPosition(JsonObject args) {
		return args.has("x") && args.has("y") && args.has("z");
	}

	private static String position(JsonObject args) {
		return coord(args, "x") + " " + coord(args, "y") + " " + coord(args, "z");
	}

	private static String coord(JsonObject args, String key) {
		if (!args.has(key) || !args.get(key).isJsonPrimitive() || !args.get(key).getAsJsonPrimitive().isNumber()) {
			throw new IllegalArgumentException("missing coordinate " + key);
		}
		return String.format(Locale.ROOT, "%.2f", args.get(key).getAsDouble());
	}

	private static double coordDouble(JsonObject args, String key) {
		if (!args.has(key) || !args.get(key).isJsonPrimitive() || !args.get(key).getAsJsonPrimitive().isNumber()) {
			throw new IllegalArgumentException("missing coordinate " + key);
		}
		return args.get(key).getAsDouble();
	}

	private static int clampInt(JsonObject args, String key, int fallback, int min, int max) {
		int value = args.has(key) ? args.get(key).getAsInt() : fallback;
		return Math.max(min, Math.min(max, value));
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
		for (String prefix : READ_ONLY_COMMAND_PREFIXES) {
			if (normalized.equals(prefix) || normalized.startsWith(prefix + " ")) {
				return true;
			}
		}
		return false;
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

	private record ChainCommand(String command, Vec3 nextLookOrigin) {
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

		private boolean failure() {
			return completed && !success;
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
			if (requester != null) {
				requester.sendSystemMessage(Component.literal("[Mina command] " + message.getString()));
			}
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
