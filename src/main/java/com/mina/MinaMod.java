package com.mina;

import com.mina.config.MinaConfig;
import com.mina.game.MinaActionExecutor;
import com.mina.game.MinaCommands;
import com.mina.game.MinaCompanionTicker;
import com.mina.game.MinaSnapshotter;
import com.mina.game.MinaTestCommands;
import com.mina.game.MinaTurnController;
import com.mina.net.SidecarClient;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class MinaMod implements ModInitializer {
	public static final String MOD_ID = "mina";
	public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

	@Override
	public void onInitialize() {
		MinaConfig config = MinaConfig.load();
		SidecarClient sidecarClient = new SidecarClient();
		MinaSnapshotter snapshotter = new MinaSnapshotter();
		MinaActionExecutor actionExecutor = new MinaActionExecutor();
		MinaTurnController turnController = new MinaTurnController(config, sidecarClient, snapshotter, actionExecutor);
		MinaCommands commands = new MinaCommands(config, sidecarClient, turnController);
		MinaTestCommands testCommands = new MinaTestCommands(config, snapshotter, turnController);
		MinaCompanionTicker companionTicker = new MinaCompanionTicker(config, sidecarClient, snapshotter, actionExecutor);

		commands.register();
		testCommands.register();
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			companionTicker.onEndServerTick(server);
		});
		ServerLifecycleEvents.SERVER_STOPPING.register(server -> sidecarClient.close());

		LOGGER.info("Initialized mina");
	}
}
