package com.mina.client;

import com.mina.MinaMod;
import net.fabricmc.api.ClientModInitializer;

public final class MinaClient implements ClientModInitializer {
	@Override
	public void onInitializeClient() {
		MinaMod.LOGGER.info("Initializing mina client");
	}
}
